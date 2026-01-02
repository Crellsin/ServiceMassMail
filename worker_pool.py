import threading
import time
import logging
import json
from queue import Empty
from typing import Optional
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, Future

from queue_manager import QueueManager, EmailRequest
from logger_engine import setup_logger
from email_sender import EmailSender, EmailMessage, EmailFormat, EmailPriority

class EmailWorker:
    """Worker that processes email batches from the queue."""
    
    def __init__(self, worker_id: int, queue_manager: QueueManager):
        """
        Initialize an email worker.
        
        Args:
            worker_id: Unique ID for this worker
            queue_manager: QueueManager instance to get batches from
        """
        self.worker_id = worker_id
        self.queue_manager = queue_manager
        self.logger = setup_logger(f"Worker-{worker_id}", f"logs/worker_{worker_id}.log")
        self.running = False
        self.current_batch = None
        self.email_sender = EmailSender()
        
    def _is_html(self, body: str) -> bool:
        """
        Simple heuristic to check if body contains HTML.
        
        Args:
            body: Email body text
            
        Returns:
            True if body appears to contain HTML, False otherwise
        """
        # Basic check for common HTML tags
        html_tags = ['<div', '<p>', '<br', '<table', '<tr', '<td', '<th', '<ul', '<ol', '<li', '<h1', '<h2', '<h3', '<h4', '<h5', '<h6']
        return any(tag in body.lower() for tag in html_tags)
    
    def process_batch(self, batch_data: dict) -> tuple[bool, Optional[dict]]:
        """
        Process a batch of emails.
        
        Args:
            batch_data: Batch data dictionary from queue_manager
            
        Returns:
            Tuple of (success, updated_batch_data)
            - success: True if all emails were sent successfully, False otherwise
            - updated_batch_data: If there are failed emails, returns updated batch data
              with only failed emails (and their retry counts incremented). 
              Returns None if all emails were successful.
        """
        batch_file = batch_data["file"]
        
        # Validate batch data structure
        if not isinstance(batch_data.get("data"), dict):
            self.logger.error(f"Batch {batch_file.name} has invalid data structure: 'data' is not a dict")
            return False, None
        
        original_data = batch_data["data"]
        emails = original_data.get("emails", [])
        if not isinstance(emails, list):
            self.logger.error(f"Batch {batch_file.name} has invalid 'emails' field: not a list")
            return False, None
        
        self.logger.info(f"Processing batch {batch_file.name} with {len(emails)} emails")
        
        successful_emails = 0
        failed_email_dicts = []  # Will store the original email dicts that failed
        
        for email_dict in emails:
            try:
                # Validate email_dict is a dictionary
                if not isinstance(email_dict, dict):
                    self.logger.error(f"Email entry is not a dict: {type(email_dict)}")
                    email_dict["status"] = "failed"
                    email_dict["retry_count"] = email_dict.get("retry_count", 0) + 1
                    failed_email_dicts.append(email_dict)
                    continue
                
                # Convert dict back to EmailRequest object
                email_request = EmailRequest(**email_dict)
                
                # Determine email format based on content
                if self._is_html(email_request.body):
                    email_format = EmailFormat.HTML
                else:
                    email_format = EmailFormat.PLAIN
                
                # Create EmailMessage from EmailRequest
                email_message = EmailMessage(
                    subject=email_request.subject,
                    body=email_request.body,
                    to_email=email_request.to_email,
                    from_email=email_request.from_email,
                    format=email_format,
                    priority=EmailPriority(email_request.priority)
                )
                
                self.logger.debug(f"Sending email to {email_request.to_email}")
                
                # Actually send the email
                success = self.email_sender.send_email(email_message)
                
                if success:
                    successful_emails += 1
                    email_dict["status"] = "sent"
                    self.logger.debug(f"Successfully sent email {email_request.request_id}")
                else:
                    self.logger.error(f"Failed to send email {email_request.request_id}")
                    # Update status and increment retry count for failed email
                    email_dict["status"] = "failed"
                    email_dict["retry_count"] = email_dict.get("retry_count", 0) + 1
                    email_dict["last_error"] = "Email sending failed after retries"
                    failed_email_dicts.append(email_dict)
                
            except (TypeError, KeyError) as e:
                # These are likely due to missing required fields in email_dict
                self.logger.error(f"Failed to create EmailRequest from dict: {e}, dict: {email_dict}")
                email_dict["status"] = "failed"
                email_dict["retry_count"] = email_dict.get("retry_count", 0) + 1
                failed_email_dicts.append(email_dict)
            except Exception as e:
                self.logger.error(f"Failed to process email {email_dict.get('request_id')}: {e}")
                email_dict["status"] = "failed"
                email_dict["retry_count"] = email_dict.get("retry_count", 0) + 1
                failed_email_dicts.append(email_dict)
        
        # Check if all emails were successful
        if len(failed_email_dicts) == 0:
            self.logger.info(f"Batch {batch_file.name} processed successfully: {successful_emails} emails sent")
            return True, None
        else:
            self.logger.warning(
                f"Batch {batch_file.name} completed with {len(failed_email_dicts)} failures. "
                f"Successful: {successful_emails}, Failed: {len(failed_email_dicts)}"
            )
            
            # Create updated batch data with only failed emails (with updated status and retry count)
            updated_data = original_data.copy()
            updated_data["emails"] = failed_email_dicts
            updated_data["status"] = "pending"  # Reset status so it can be retried
            updated_data["updated_at"] = datetime.now().isoformat()
            
            return False, updated_data
    
    def run(self):
        """Main worker loop."""
        self.running = True
        self.logger.info(f"Worker {self.worker_id} started")
        
        consecutive_failures = 0
        max_consecutive_failures = 3
        base_retry_delay = 5  # seconds
        max_retry_delay = 60  # seconds
        
        while self.running:
            try:
                # Get next batch (maximum 1 batch at a time)
                batches = self.queue_manager.get_next_batch(max_batches=1)
                
                if not batches:
                    # No batches available, wait a bit
                    time.sleep(base_retry_delay)
                    consecutive_failures = 0  # Reset failures on successful check
                    continue
                
                # Process the batch
                batch_data = batches[0]
                self.current_batch = batch_data
                
                success, updated_batch_data = self.process_batch(batch_data)
                
                # Mark batch as complete
                self.queue_manager.mark_batch_complete(
                    batch_data["file"], 
                    successful=success,
                    updated_data=updated_batch_data
                )
                
                self.current_batch = None
                consecutive_failures = 0  # Reset on successful batch processing
                
            except json.JSONDecodeError as e:
                consecutive_failures += 1
                retry_delay = min(base_retry_delay * (2 ** (consecutive_failures - 1)), max_retry_delay)
                self.logger.error(f"JSON decoding error in worker {self.worker_id}: {e}. "
                                 f"Retry in {retry_delay} seconds (failure #{consecutive_failures})")
                time.sleep(retry_delay)
                
            except Exception as e:
                consecutive_failures += 1
                retry_delay = min(base_retry_delay * (2 ** (consecutive_failures - 1)), max_retry_delay)
                self.logger.error(f"Error in worker {self.worker_id}: {e}. "
                                 f"Retry in {retry_delay} seconds (failure #{consecutive_failures})")
                time.sleep(retry_delay)
                
                # If we've hit too many consecutive failures, take a longer break
                if consecutive_failures >= max_consecutive_failures:
                    self.logger.warning(f"Worker {self.worker_id} has had {consecutive_failures} consecutive failures. "
                                       f"Taking extended break of {max_retry_delay} seconds.")
                    time.sleep(max_retry_delay)
                    consecutive_failures = 0  # Reset after extended break
    
    def stop(self):
        """Stop the worker."""
        self.running = False
        self.logger.info(f"Worker {self.worker_id} stopped")

class WorkerPool:
    """Manages a pool of email workers."""
    
    def __init__(self, queue_manager: QueueManager, num_workers: int = 3):
        """
        Initialize the worker pool.
        
        Args:
            queue_manager: QueueManager instance
            num_workers: Number of worker threads to create
        """
        self.queue_manager = queue_manager
        self.num_workers = num_workers
        self.workers = []
        self.threads = []
        self.logger = setup_logger("WorkerPool", "logs/worker_pool.log")
        
        # Create worker directories
        Path("logs").mkdir(exist_ok=True)
        
    def start(self):
        """Start all worker threads."""
        self.logger.info(f"Starting worker pool with {self.num_workers} workers")
        
        for i in range(self.num_workers):
            worker = EmailWorker(i + 1, self.queue_manager)
            thread = threading.Thread(target=worker.run, daemon=True)
            
            self.workers.append(worker)
            self.threads.append(thread)
            
            thread.start()
            self.logger.debug(f"Started worker {i + 1}")
    
    def stop(self):
        """Stop all worker threads."""
        self.logger.info("Stopping worker pool")
        
        for worker in self.workers:
            worker.stop()
        
        # Wait for threads to finish (with timeout)
        for thread in self.threads:
            thread.join(timeout=5)
        
        self.logger.info("Worker pool stopped")
    
    def get_status(self) -> dict:
        """
        Get status of all workers.
        
        Returns:
            Dictionary with worker status information
        """
        status = {
            "total_workers": len(self.workers),
            "active_workers": 0,
            "workers": []
        }
        
        for worker in self.workers:
            worker_status = {
                "worker_id": worker.worker_id,
                "running": worker.running,
                "current_batch": worker.current_batch["file"].name if worker.current_batch else None
            }
            status["workers"].append(worker_status)
            
            if worker.running:
                status["active_workers"] += 1
        
        return status

class BatchProcessor:
    """
    Simple batch processor for testing and manual operation.
    Can be used independently of the worker pool.
    """
    
    def __init__(self, queue_manager: QueueManager):
        self.queue_manager = queue_manager
        self.logger = setup_logger("BatchProcessor", "logs/batch_processor.log")
    
    def process_single_batch(self) -> bool:
        """
        Process a single batch manually.
        
        Returns:
            True if a batch was processed, False if no batches available
        """
        batches = self.queue_manager.get_next_batch(max_batches=1)
        
        if not batches:
            self.logger.info("No batches available for processing")
            return False
        
        batch_data = batches[0]
        self.logger.info(f"Processing batch {batch_data['file'].name}")
        
        # Create a temporary worker to process this batch
        worker = EmailWorker(0, self.queue_manager)
        success, updated_batch_data = worker.process_batch(batch_data)
        
        # Mark batch as complete
        self.queue_manager.mark_batch_complete(
            batch_data["file"], 
            successful=success,
            updated_data=updated_batch_data
        )
        
        return True

# Example usage
if __name__ == "__main__":
    # Initialize queue manager
    qm = QueueManager()
    
    # Add some test emails
    for i in range(5):
        email = qm.create_email_request(
            subject=f"Test Email {i+1}",
            body=f"This is test email body {i+1}.",
            to_email=f"test{i+1}@example.com"
        )
        qm.add_email(email)
    
    print(f"Added 5 test emails to queue")
    
    # Get queue stats
    stats = qm.get_queue_stats()
    print(f"Queue stats: {stats}")
    
    # Test batch processor
    processor = BatchProcessor(qm)
    
    # Process batches until none left
    batch_count = 0
    while processor.process_single_batch():
        batch_count += 1
    
    print(f"Processed {batch_count} batches")
    
    # Check queue stats again
    stats = qm.get_queue_stats()
    print(f"Queue stats after processing: {stats}")
