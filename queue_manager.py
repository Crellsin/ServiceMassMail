import json
import os
import threading
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import uuid
import logging

from logger_engine import setup_logger

@dataclass
class EmailRequest:
    """Represents an email request to be queued."""
    request_id: str
    subject: str
    body: str
    to_email: str
    from_email: Optional[str] = None
    template_name: Optional[str] = None
    template_vars: Optional[Dict[str, Any]] = None
    priority: int = 1  # 1=High, 2=Normal, 3=Low
    status: str = "pending"  # pending, processing, sent, failed
    created_at: str = None
    retry_count: int = 0
    max_retries: int = 3

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()

class QueueManager:
    """Manages email queue using JSON files with pagination (100 emails per batch)."""
    
    def __init__(self, queue_dir: str = "data/queue", batch_size: int = 100, dead_letter_dir: str = "data/dead_letter"):
        """
        Initialize the queue manager.
        
        Args:
            queue_dir: Directory to store queue batch files
            batch_size: Number of emails per batch file
            dead_letter_dir: Directory to store permanently failed emails
        """
        self.queue_dir = Path(queue_dir)
        self.batch_size = batch_size
        self.dead_letter_dir = Path(dead_letter_dir)
        self.lock = threading.RLock()
        
        # Create queue directory if it doesn't exist
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        # Create dead letter directory if it doesn't exist
        self.dead_letter_dir.mkdir(parents=True, exist_ok=True)
        
        # Set up logger
        self.logger = setup_logger(__name__, 'logs/queue_manager.log')
        
        # Initialize batch index
        self._update_batch_index()
    
    def _update_batch_index(self):
        """Scan queue directory and update the list of batch files."""
        self.batch_files = sorted(list(self.queue_dir.glob("batch_*.json")))
    
    def _get_current_batch_file(self) -> Path:
        """Get the current batch file (most recent one that isn't full)."""
        self._update_batch_index()
        
        if not self.batch_files:
            # No batch files exist, create first one
            return self.queue_dir / f"batch_001.json"
        
        # Get the most recent batch file
        latest_batch = self.batch_files[-1]
        
        # Check if it's full
        with open(latest_batch, 'r') as f:
            data = json.load(f)
        
        if len(data.get("emails", [])) < self.batch_size:
            return latest_batch
        else:
            # Create new batch file with next sequence number
            batch_num = len(self.batch_files) + 1
            return self.queue_dir / f"batch_{batch_num:03d}.json"
    
    def add_email(self, email_request: EmailRequest) -> str:
        """
        Add an email request to the queue.
        
        Args:
            email_request: EmailRequest object
            
        Returns:
            The request ID
        """
        with self.lock:
            batch_file = self._get_current_batch_file()
            
            # Load existing data or initialize
            data = {}
            if batch_file.exists():
                try:
                    with open(batch_file, 'r') as f:
                        data = json.load(f)
                except json.JSONDecodeError:
                    # If file is corrupted, initialize fresh data
                    data = {
                        "batch_id": batch_file.stem,
                        "created_at": datetime.now().isoformat(),
                        "emails": []
                    }
            else:
                data = {
                    "batch_id": batch_file.stem,
                    "created_at": datetime.now().isoformat(),
                    "emails": []
                }
            
            # Add email request
            data["emails"].append(asdict(email_request))
            
            # Atomic write: write to temp file then rename
            temp_file = None
            try:
                # Create temporary file in same directory for atomic rename
                temp_fd, temp_path = tempfile.mkstemp(
                    suffix='.json',
                    dir=self.queue_dir,
                    text=True
                )
                temp_file = os.fdopen(temp_fd, 'w')
                
                # Write JSON to temporary file
                json.dump(data, temp_file, indent=2)
                temp_file.close()
                
                # Atomic rename (works on Unix and Windows)
                os.replace(temp_path, batch_file)
            except Exception as e:
                # Clean up temp file if it exists
                if temp_file and not temp_file.closed:
                    temp_file.close()
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise e
            
            return email_request.request_id
    
    def create_email_request(
        self,
        subject: str,
        body: str,
        to_email: str,
        template_name: Optional[str] = None,
        template_vars: Optional[Dict[str, Any]] = None,
        priority: int = 2
    ) -> EmailRequest:
        """
        Create an EmailRequest object with a unique ID.
        
        Args:
            subject: Email subject
            body: Email body (can be plain text or HTML)
            to_email: Recipient email address
            from_email: Sender email address (optional, uses default from config)
            template_name: Name of template to use (optional)
            template_vars: Template variables for substitution (optional)
            priority: Priority level (1=High, 2=Normal, 3=Low)
            
        Returns:
            EmailRequest object
        """
        request_id = str(uuid.uuid4())
        
        return EmailRequest(
            request_id=request_id,
            subject=subject,
            body=body,
            to_email=to_email,
            template_name=template_name,
            template_vars=template_vars,
            priority=priority
        )
    
    def get_next_batch(self, max_batches: int = 1) -> List[Dict]:
        """
        Get the next batch(es) of emails for processing.
        
        Args:
            max_batches: Maximum number of batches to retrieve
            
        Returns:
            List of batch data dictionaries
        """
        with self.lock:
            self._update_batch_index()
            
            batches = []
            for batch_file in self.batch_files[:max_batches]:
                # Skip if file doesn't exist or is empty
                if not batch_file.exists() or batch_file.stat().st_size == 0:
                    continue
                
                try:
                    with open(batch_file, 'r') as f:
                        batch_data = json.load(f)
                except json.JSONDecodeError as e:
                    # Log and skip invalid JSON files
                    continue
                
                # Skip batches already being processed or marked as failed
                status = batch_data.get("status")
                if status in ["processing", "failed"]:
                    continue
                
                # Check if batch has any emails left to process
                emails = batch_data.get("emails", [])
                if not emails:
                    # Empty batch, mark as completed and skip
                    self.mark_batch_complete(batch_file, successful=True)
                    continue
                
                # Mark batch as processing
                batch_data["status"] = "processing"
                batch_data["processing_started_at"] = datetime.now().isoformat()
                
                # Atomic write for status update
                temp_file = None
                temp_path = None
                try:
                    # Create temporary file in same directory for atomic rename
                    temp_fd, temp_path = tempfile.mkstemp(
                        suffix='.json',
                        dir=self.queue_dir,
                        text=True
                    )
                    temp_file = os.fdopen(temp_fd, 'w')
                    
                    # Write JSON to temporary file
                    json.dump(batch_data, temp_file, indent=2)
                    temp_file.close()
                    
                    # Atomic rename
                    os.replace(temp_path, batch_file)
                except Exception:
                    # Clean up temp file if it exists
                    if temp_file and not temp_file.closed:
                        temp_file.close()
                    if temp_path and os.path.exists(temp_path):
                        os.unlink(temp_path)
                    continue
                
                batches.append({
                    "file": batch_file,
                    "data": batch_data
                })
            
            return batches
    
    def move_to_dead_letter(self, email_dict: Dict[str, Any], failure_reason: str = "Max retries exceeded"):
        """
        Move an email that has permanently failed to the dead letter queue.
        
        Args:
            email_dict: The email dictionary (from the batch)
            failure_reason: Reason for failure (default: "Max retries exceeded")
        """
        # Create dead letter entry with additional metadata
        dead_letter_entry = {
            "original_email": email_dict,
            "failure_reason": failure_reason,
            "moved_to_dead_letter_at": datetime.now().isoformat(),
            "can_be_retried": False  # Can be set to True if manually corrected
        }
        
        # Use request_id as filename
        request_id = email_dict.get("request_id", "unknown")
        dead_letter_file = self.dead_letter_dir / f"dead_letter_{request_id}.json"
        
        # Write to dead letter file
        try:
            with open(dead_letter_file, 'w') as f:
                json.dump(dead_letter_entry, f, indent=2)
            self.logger.warning(f"Moved email {request_id} to dead letter: {failure_reason}")
        except Exception as e:
            self.logger.error(f"Failed to write dead letter file for {request_id}: {e}")
    
    def update_batch(self, batch_file: Path, updated_data: Dict[str, Any]):
        """
        Update a batch file with new data (e.g., after partial processing).
        
        Args:
            batch_file: Path to the batch file
            updated_data: Updated batch data
        """
        if not batch_file.exists():
            return
        
        # Add metadata
        if "status" not in updated_data:
            updated_data["status"] = "pending"
        if "updated_at" not in updated_data:
            updated_data["updated_at"] = datetime.now().isoformat()
        
        # Atomic write
        temp_file = None
        temp_path = None
        try:
            # Create temporary file in same directory for atomic rename
            temp_fd, temp_path = tempfile.mkstemp(
                suffix='.json',
                dir=self.queue_dir,
                text=True
            )
            temp_file = os.fdopen(temp_fd, 'w')
            
            # Write JSON to temporary file
            json.dump(updated_data, temp_file, indent=2)
            temp_file.close()
            
            # Atomic rename
            os.replace(temp_path, batch_file)
        except Exception:
            # Clean up temp file if it exists
            if temp_file and not temp_file.closed:
                temp_file.close()
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            # Fallback to non-atomic write
            with open(batch_file, 'w') as f:
                json.dump(updated_data, f, indent=2)
    
    def mark_batch_complete(self, batch_file: Path, successful: bool = True, updated_data: Optional[Dict[str, Any]] = None):
        """
        Mark a batch as completed.
        
        Args:
            batch_file: Path to the batch file
            successful: Whether processing was successful (all emails sent)
            updated_data: Updated batch data if partial success (contains only remaining emails)
        """
        with self.lock:
            if not batch_file.exists():
                return
            
            if successful:
                # Delete the batch file if all emails were successful
                batch_file.unlink(missing_ok=True)
                return
            
            # If we have updated_data, we need to filter out emails that have exceeded max_retries
            if updated_data is not None:
                emails = updated_data.get("emails", [])
                remaining_emails = []
                for email in emails:
                    retry_count = email.get("retry_count", 0)
                    max_retries = email.get("max_retries", 3)
                    if retry_count < max_retries:
                        remaining_emails.append(email)
                    else:
                        # Email has exceeded max retries, move to dead letter
                        failure_reason = email.get("last_error", "Max retries exceeded")
                        self.move_to_dead_letter(email, failure_reason)
                
                if remaining_emails:
                    # Update batch with emails that can still be retried
                    updated_data["emails"] = remaining_emails
                    updated_data["status"] = "pending"
                    updated_data["last_retry_at"] = datetime.now().isoformat()
                    self.update_batch(batch_file, updated_data)
                else:
                    # All emails have exceeded max retries, delete the file
                    batch_file.unlink(missing_ok=True)
                return
            
            # Traditional failed batch handling (no updated_data provided)
            try:
                if batch_file.exists() and batch_file.stat().st_size > 0:
                    with open(batch_file, 'r') as f:
                        data = json.load(f)
                else:
                    # If file is empty or doesn't exist, just delete it
                    batch_file.unlink(missing_ok=True)
                    return
            except json.JSONDecodeError:
                # If file has invalid JSON, just delete it
                batch_file.unlink(missing_ok=True)
                return
            
            # Check if any emails are left to retry
            emails = data.get("emails", [])
            if not emails:
                # No emails left, delete the file
                batch_file.unlink(missing_ok=True)
                return
            
            # Increment retry count for remaining emails
            for email in emails:
                email["retry_count"] = email.get("retry_count", 0) + 1
            
            # Check if any emails have exceeded max retries
            remaining_emails = []
            for email in emails:
                retry_count = email.get("retry_count", 0)
                max_retries = email.get("max_retries", 3)
                if retry_count < max_retries:
                    remaining_emails.append(email)
                else:
                    # Email has exceeded max retries, move to dead letter
                    failure_reason = email.get("last_error", "Max retries exceeded")
                    self.move_to_dead_letter(email, failure_reason)
            
            if remaining_emails:
                # Update batch with emails that can still be retried
                data["emails"] = remaining_emails
                data["status"] = "pending"
                data["last_retry_at"] = datetime.now().isoformat()
                self.update_batch(batch_file, data)
            else:
                # All emails have exceeded max retries, delete the file
                batch_file.unlink(missing_ok=True)
    
    def get_queue_stats(self) -> Dict[str, Any]:
        """
        Get queue statistics.
        
        Returns:
            Dictionary with queue statistics
        """
        self._update_batch_index()
        
        total_emails = 0
        batches_info = []
        
        for batch_file in self.batch_files:
            # Skip if file doesn't exist or is empty
            if not batch_file.exists() or batch_file.stat().st_size == 0:
                continue
            
            try:
                with open(batch_file, 'r') as f:
                    data = json.load(f)
            except json.JSONDecodeError:
                # Skip invalid JSON files in stats
                continue
            
            email_count = len(data.get("emails", []))
            total_emails += email_count
            
            batches_info.append({
                "batch_id": data.get("batch_id"),
                "email_count": email_count,
                "status": data.get("status", "pending"),
                "created_at": data.get("created_at")
            })
        
        return {
            "total_batches": len(self.batch_files),
            "total_emails": total_emails,
            "batch_size": self.batch_size,
            "batches": batches_info
        }
    
    def clear_queue(self):
        """Clear all emails from the queue."""
        for batch_file in self.queue_dir.glob("batch_*.json"):
            batch_file.unlink()
        
        self._update_batch_index()

# Example usage
if __name__ == "__main__":
    # Initialize queue manager
    qm = QueueManager()
    
    # Create a test email request
    email = qm.create_email_request(
        subject="Test Email",
        body="This is a test email body.",
        to_email="test@example.com"
    )
    
    # Add to queue
    request_id = qm.add_email(email)
    print(f"Added email with ID: {request_id}")
    
    # Get queue stats
    stats = qm.get_queue_stats()
    print(f"Queue stats: {json.dumps(stats, indent=2)}")
