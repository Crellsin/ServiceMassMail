import json
import os
import threading
import tempfile
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import uuid

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
    status: str = "pending"
    created_at: str = None
    retry_count: int = 0
    max_retries: int = 3

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()

class QueueManager:
    """Manages email queue using one JSON file per email."""

    def __init__(self, queue_dir: str = "data/queue", batch_size: int = 1,
                 dead_letter_dir: str = "data/dead_letter", trash_dir: str = "data/trash"):
        self.queue_dir = Path(queue_dir)
        self.batch_size = batch_size
        self.dead_letter_dir = Path(dead_letter_dir)
        self.trash_dir = Path(trash_dir)
        self.lock = threading.RLock()
        self._dirty = True

        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.dead_letter_dir.mkdir(parents=True, exist_ok=True)
        self.trash_dir.mkdir(parents=True, exist_ok=True)

        self.logger = setup_logger(__name__, 'logs/queue_manager.log')
        self._update_batch_index()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _new_batch_path(self) -> Path:
        """Generate a unique, collision-free batch file path."""
        ts_ms = int(time.time() * 1000)
        uid = uuid.uuid4().hex[:8]
        return self.queue_dir / f"batch_{ts_ms}_{uid}.json"

    def _update_batch_index(self):
        """Rebuild the sorted list of pending batch files (skipped when not dirty)."""
        if not self._dirty:
            return
        self.batch_files = sorted([
            f for f in self.queue_dir.glob("batch_*.json")
            if ".processing" not in f.name
        ])
        self._dirty = False

    def _atomic_write(self, data: dict, dest: Path):
        """Write *data* to *dest* atomically: temp file → fsync → rename."""
        temp_file = None
        temp_path = None
        try:
            temp_fd, temp_path = tempfile.mkstemp(
                suffix='.json', dir=self.queue_dir, text=True
            )
            temp_file = os.fdopen(temp_fd, 'w')
            json.dump(data, temp_file, indent=2)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_file.close()
            os.replace(temp_path, dest)
        except Exception:
            if temp_file and not temp_file.closed:
                temp_file.close()
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
            raise

    def _move_to_trash(self, batch_file: Path, reason: str = "processed"):
        if not batch_file.exists():
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        trash_name = f"{batch_file.stem}_{timestamp}_{reason}.json"
        trash_path = self.trash_dir / trash_name
        try:
            shutil.move(str(batch_file), str(trash_path))
            self.logger.info(f"Moved {batch_file.name} to trash ({reason})")
        except Exception as e:
            self.logger.error(f"Failed to move {batch_file.name} to trash: {e}")
            try:
                shutil.copy2(str(batch_file), str(trash_path))
                batch_file.unlink(missing_ok=True)
            except Exception as e2:
                self.logger.error(f"Failed to copy-delete {batch_file.name}: {e2}")
        self._dirty = True

    def _cleanup_stale_processing_files(self):
        stale_threshold = 3600
        current_time = time.time()
        for processing_file in self.queue_dir.glob("*.processing.json"):
            try:
                if current_time - processing_file.stat().st_mtime > stale_threshold:
                    self.logger.warning(
                        f"Stale processing file {processing_file.name}, moving to trash"
                    )
                    self._move_to_trash(processing_file, reason="stale_processing")
            except Exception as e:
                self.logger.error(f"Error checking stale file {processing_file}: {e}")

    # ------------------------------------------------------------------
    # mark_batch_complete helpers
    # ------------------------------------------------------------------

    def _handle_successful_batch(self, batch_file: Path, data: dict):
        for email in data.get("emails", []):
            if email.get("status") == "pending":
                email["status"] = "sent"
        data["status"] = "completed"
        self.update_batch(batch_file, data)
        self._move_to_trash(batch_file, reason="success")

    def _handle_retryable_batch(self, batch_file: Path, emails: list):
        remaining = []
        for email in emails:
            if email.get("retry_count", 0) < email.get("max_retries", 3):
                remaining.append(email)
            else:
                self.move_to_dead_letter(
                    email, email.get("last_error", "Max retries exceeded")
                )

        if not remaining:
            self._move_to_trash(batch_file, reason="max_retries_exceeded")
            return

        batch_id = batch_file.stem.replace(".processing", "")
        updated = {
            "batch_id": batch_id,
            "emails": remaining,
            "status": "pending",
            "last_retry_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        self.update_batch(batch_file, updated)
        if ".processing" in batch_file.name:
            new_path = batch_file.with_name(batch_id + ".json")
            batch_file.rename(new_path)
            self._dirty = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_email(self, email_request: EmailRequest) -> str:
        with self.lock:
            batch_file = self._new_batch_path()
            data = {
                "batch_id": batch_file.stem,
                "created_at": datetime.now().isoformat(),
                "emails": [asdict(email_request)],
            }
            self._atomic_write(data, batch_file)
            self._dirty = True
            return email_request.request_id

    def create_email_request(
        self,
        subject: str,
        body: str,
        to_email: str,
        template_name: Optional[str] = None,
        template_vars: Optional[Dict[str, Any]] = None,
        priority: int = 2,
    ) -> EmailRequest:
        return EmailRequest(
            request_id=str(uuid.uuid4()),
            subject=subject,
            body=body,
            to_email=to_email,
            template_name=template_name,
            template_vars=template_vars,
            priority=priority,
        )

    def get_next_batch(self, max_batches: int = 1) -> List[Dict]:
        with self.lock:
            self._cleanup_stale_processing_files()
            self._update_batch_index()

            batches = []
            for batch_file in self.batch_files[:max_batches]:
                if not batch_file.exists() or batch_file.stat().st_size == 0:
                    continue

                processing_file = batch_file.with_name(
                    batch_file.stem + ".processing.json"
                )
                try:
                    batch_file.rename(processing_file)
                    self._dirty = True
                except (FileNotFoundError, PermissionError, OSError) as e:
                    self.logger.debug(f"Could not claim {batch_file}: {e}")
                    continue

                try:
                    with open(processing_file, 'r') as f:
                        batch_data = json.load(f)
                except json.JSONDecodeError as e:
                    self.logger.error(f"Invalid JSON in {processing_file}: {e}")
                    self._move_to_trash(processing_file, reason="invalid_json")
                    continue

                if not batch_data.get("emails"):
                    self._move_to_trash(processing_file, reason="empty_batch")
                    continue

                batch_data["status"] = "processing"
                batch_data["processing_started_at"] = datetime.now().isoformat()

                try:
                    self._atomic_write(batch_data, processing_file)
                except Exception as e:
                    self.logger.error(
                        f"Failed to update processing status for {processing_file}: {e}"
                    )
                    self._move_to_trash(processing_file, reason="update_failed")
                    continue

                batches.append({"file": processing_file, "data": batch_data})

            return batches

    def move_to_dead_letter(self, email_dict: Dict[str, Any], failure_reason: str = "Max retries exceeded"):
        dead_letter_entry = {
            "original_email": email_dict,
            "failure_reason": failure_reason,
            "moved_to_dead_letter_at": datetime.now().isoformat(),
            "can_be_retried": False,
        }
        request_id = email_dict.get("request_id", "unknown")
        dead_letter_file = self.dead_letter_dir / f"dead_letter_{request_id}.json"
        try:
            with open(dead_letter_file, 'w') as f:
                json.dump(dead_letter_entry, f, indent=2)
            self.logger.warning(f"Moved email {request_id} to dead letter: {failure_reason}")
        except Exception as e:
            self.logger.error(f"Failed to write dead letter file for {request_id}: {e}")

    def update_batch(self, batch_file: Path, updated_data: Dict[str, Any]):
        if not batch_file.exists():
            return
        updated_data.setdefault("status", "pending")
        updated_data.setdefault("updated_at", datetime.now().isoformat())
        try:
            self._atomic_write(updated_data, batch_file)
        except Exception:
            with open(batch_file, 'w') as f:
                json.dump(updated_data, f, indent=2)

    def mark_batch_complete(
        self,
        batch_file: Path,
        successful: bool = True,
        updated_data: Optional[Dict[str, Any]] = None,
    ):
        with self.lock:
            if not batch_file.exists():
                return

            try:
                if batch_file.stat().st_size == 0:
                    self._move_to_trash(batch_file, reason="empty")
                    return
                with open(batch_file, 'r') as f:
                    data = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                self._move_to_trash(batch_file, reason="corrupted")
                return

            data["completed_at"] = datetime.now().isoformat()

            if successful:
                self._handle_successful_batch(batch_file, data)
                return

            # Determine which email list to work from
            emails = (
                updated_data.get("emails", [])
                if updated_data is not None
                else data.get("emails", [])
            )

            # If caller didn't supply pre-incremented counts, increment now
            if updated_data is None:
                for email in emails:
                    email["retry_count"] = email.get("retry_count", 0) + 1

            if not emails:
                self._move_to_trash(batch_file, reason="empty")
                return

            self._handle_retryable_batch(batch_file, emails)

    def get_queue_stats(self) -> Dict[str, Any]:
        self._update_batch_index()
        total_emails = 0
        batches_info = []
        for batch_file in self.batch_files:
            if not batch_file.exists() or batch_file.stat().st_size == 0:
                continue
            try:
                with open(batch_file, 'r') as f:
                    data = json.load(f)
            except json.JSONDecodeError:
                continue
            email_count = len(data.get("emails", []))
            total_emails += email_count
            batches_info.append({
                "batch_id": data.get("batch_id"),
                "email_count": email_count,
                "status": data.get("status", "pending"),
                "created_at": data.get("created_at"),
            })
        return {
            "total_batches": len(self.batch_files),
            "total_emails": total_emails,
            "batch_size": self.batch_size,
            "batches": batches_info,
        }

    def clear_queue(self):
        for batch_file in self.queue_dir.glob("batch_*.json"):
            batch_file.unlink(missing_ok=True)
        for processing_file in self.queue_dir.glob("*.processing.json"):
            processing_file.unlink(missing_ok=True)
        self._dirty = True
        self._update_batch_index()


# if __name__ == "__main__":
#     qm = QueueManager()

#     for i in range(5):
#         email = qm.create_email_request(
#             subject=f"Test Email {i + 1}",
#             body=f"This is test email body {i + 1}.",
#             to_email="liderador123@gmail.com",
#         )
#         qm.add_email(email)

#     stats = qm.get_queue_stats()
#     print(f"Queue stats: {json.dumps(stats, indent=2)}")
