import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import uuid

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
    
    def __init__(self, queue_dir: str = "data/queue", batch_size: int = 100):
        """
        Initialize the queue manager.
        
        Args:
            queue_dir: Directory to store queue batch files
            batch_size: Number of emails per batch file
        """
        self.queue_dir = Path(queue_dir)
        self.batch_size = batch_size
        self.lock = threading.Lock()
        
        # Create queue directory if it doesn't exist
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        
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
            if batch_file.exists():
                with open(batch_file, 'r') as f:
                    data = json.load(f)
            else:
                data = {
                    "batch_id": batch_file.stem,
                    "created_at": datetime.now().isoformat(),
                    "emails": []
                }
            
            # Add email request
            data["emails"].append(asdict(email_request))
            
            # Save back to file
            with open(batch_file, 'w') as f:
                json.dump(data, f, indent=2)
            
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
        self._update_batch_index()
        
        batches = []
        for batch_file in self.batch_files[:max_batches]:
            with open(batch_file, 'r') as f:
                batch_data = json.load(f)
            
            # Mark batch as processing
            batch_data["status"] = "processing"
            batch_data["processing_started_at"] = datetime.now().isoformat()
            
            with open(batch_file, 'w') as f:
                json.dump(batch_data, f, indent=2)
            
            batches.append({
                "file": batch_file,
                "data": batch_data
            })
        
        return batches
    
    def mark_batch_complete(self, batch_file: Path, successful: bool = True):
        """
        Mark a batch as completed and delete the file if successful.
        
        Args:
            batch_file: Path to the batch file
            successful: Whether processing was successful
        """
        if successful:
            # Delete the batch file
            batch_file.unlink(missing_ok=True)
        else:
            # Update batch status to failed
            with open(batch_file, 'r') as f:
                data = json.load(f)
            
            data["status"] = "failed"
            data["completed_at"] = datetime.now().isoformat()
            
            with open(batch_file, 'w') as f:
                json.dump(data, f, indent=2)
    
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
            with open(batch_file, 'r') as f:
                data = json.load(f)
            
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
