import threading
import time
import logging
from queue import Empty
from typing import Optional
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, Future

from queue_manager import QueueManager, EmailRequest
from logger_engine import setup_logger

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
        
    def process_batch(self, batch_data: dict) -> bool:
        """
        Process a batch of emails.
        
        Args:
            batch_data: Batch data dictionary from queue_manager
            
        Returns:
            True if batch processed successfully, False otherwise
        """
        batch_file = batch_data["file"]
        emails = batch_data["data"].get("emails", [])
        
        self.logger.info(f"Processing batch {batch_file.name} with {len(emails)} emails")
        
        successful_emails = 0
        failed_emails = []
        
        for email_dict in emails:
            try:
                # Convert dict back to EmailRequest-like object
                email_request = EmailRequest(**email_dict)
                
                # TODO: Actually send the email (will be integrated in Phase 2)
                # For now, just simulate processing
                self.logger.debug(f"Processing email to {email_request.to_email}")
                
                # Simulate email sending
                time.sleep(0.1)  # Simulate network delay
                
                # For testing: Always succeed for now
                successful_emails += 1
                
                self.logger.debug(f"Successfully processed email {email_request.request_id}")
                
            except Exception as e:
                self.logger.error(f"Failed to process email {email_dict.get('request_id')}: {e}")
                failed_emails.append({
                    "email": email_dict,
                    "error": str(e)
                })
        
        # If all emails processed successfully, return True
        if len(failed_emails) == 0:
            self.logger.info(f"Batch {batch_file.name} processed successfully")
            return True
        else:
            self.logger.warning(f"Batch {batch_file.name} had {len(failed_emails)} failures")
            # TODO: Handle retry logic for failed emails (Phase 2)
            return False
    
    def run(self):
        """Main worker loop."""
        self.running = True
        self.logger.info(f"Worker {self.worker_id} started")
        
        while self.running:
            try:
                # Get next batch (maximum 1 batch at a time)
                batches = self.queue_manager.get_next_batch(max_batches=1)
                
                if not batches:
                    # No batches available, wait a bit
                    time.sleep(5)
                    continue
                
                # Process the batch
                batch_data = batches[0]
                self.current_batch = batch_data
                
                success = self.process_batch(batch_data)
                
                # Mark batch as complete
                self.queue_manager.mark_batch_complete(
                    batch_data["file"], 
                    successful=success
                )
                
                self.current_batch = None
                
            except Exception as e:
                self.logger.error(f"Error in worker {self.worker_id}: {e}")
                time.sleep(10)  # Wait before retrying
    
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
        success = worker.process_batch(batch_data)
        
        # Mark batch as complete
        self.queue_manager.mark_batch_complete(
            batch_data["file"], 
            successful=success
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
