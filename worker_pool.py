import threading
import time
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from queue_manager import QueueManager, EmailRequest
from logger_engine import setup_logger
from email_sender import EmailSender, EmailMessage, EmailFormat, EmailPriority


class EmailWorker:
    """Worker that processes email batches from the queue."""

    def __init__(self, worker_id: int, queue_manager: QueueManager):
        self.worker_id = worker_id
        self.queue_manager = queue_manager
        self.logger = setup_logger(f"Worker-{worker_id}", f"logs/worker_{worker_id}.log")
        self.running = False
        self.current_batch = None
        self.email_sender = EmailSender()

        # Per-worker metrics (written by worker thread, read by status thread — GIL makes
        # int/float reads atomic in CPython, so no lock needed for approximate metrics)
        self.emails_sent = 0
        self.emails_failed = 0
        self._total_latency_ms = 0.0
        self._emails_timed = 0

    @property
    def avg_latency_ms(self) -> float:
        return self._total_latency_ms / self._emails_timed if self._emails_timed > 0 else 0.0

    def _is_html(self, body: str) -> bool:
        html_tags = ['<div', '<p>', '<br', '<table', '<tr', '<td', '<th',
                     '<ul', '<ol', '<li', '<h1', '<h2', '<h3', '<h4', '<h5', '<h6']
        return any(tag in body.lower() for tag in html_tags)

    def process_batch(self, batch_data: dict) -> tuple[bool, Optional[dict]]:
        batch_file = batch_data["file"]

        if not isinstance(batch_data.get("data"), dict):
            self.logger.error(f"Batch {batch_file.name} has invalid data structure")
            return False, None

        original_data = batch_data["data"]
        emails = original_data.get("emails", [])
        if not isinstance(emails, list):
            self.logger.error(f"Batch {batch_file.name} has invalid 'emails' field")
            return False, None

        self.logger.info(f"Processing batch {batch_file.name} with {len(emails)} emails")

        successful_emails = 0
        failed_email_dicts = []

        for email_dict in emails:
            try:
                if not isinstance(email_dict, dict):
                    self.logger.error(f"Email entry is not a dict: {type(email_dict)}")
                    email_dict["status"] = "failed"
                    email_dict["retry_count"] = email_dict.get("retry_count", 0) + 1
                    failed_email_dicts.append(email_dict)
                    self.emails_failed += 1
                    continue

                email_request = EmailRequest(**email_dict)
                email_format = EmailFormat.HTML if self._is_html(email_request.body) else EmailFormat.PLAIN
                email_message = EmailMessage(
                    subject=email_request.subject,
                    body=email_request.body,
                    to_email=email_request.to_email,
                    from_email=email_request.from_email,
                    format=email_format,
                    priority=EmailPriority(email_request.priority),
                )

                t0 = time.monotonic()
                success = self.email_sender.send_email(email_message)
                elapsed_ms = (time.monotonic() - t0) * 1000
                self._total_latency_ms += elapsed_ms
                self._emails_timed += 1

                if success:
                    successful_emails += 1
                    self.emails_sent += 1
                    email_dict["status"] = "sent"
                    self.logger.debug(f"Sent {email_request.request_id}")
                else:
                    self.logger.error(f"Failed to send {email_request.request_id}")
                    email_dict["status"] = "failed"
                    email_dict["retry_count"] = email_dict.get("retry_count", 0) + 1
                    email_dict["last_error"] = "Email sending failed after retries"
                    failed_email_dicts.append(email_dict)
                    self.emails_failed += 1

            except (TypeError, KeyError) as e:
                self.logger.error(f"Failed to build EmailRequest: {e}, dict: {email_dict}")
                email_dict["status"] = "failed"
                email_dict["retry_count"] = email_dict.get("retry_count", 0) + 1
                failed_email_dicts.append(email_dict)
                self.emails_failed += 1
            except Exception as e:
                self.logger.error(f"Failed to process email {email_dict.get('request_id')}: {e}")
                email_dict["status"] = "failed"
                email_dict["retry_count"] = email_dict.get("retry_count", 0) + 1
                failed_email_dicts.append(email_dict)
                self.emails_failed += 1

        if not failed_email_dicts:
            self.logger.info(f"Batch {batch_file.name}: {successful_emails} sent")
            return True, None

        self.logger.warning(
            f"Batch {batch_file.name}: {successful_emails} sent, {len(failed_email_dicts)} failed"
        )
        updated_data = original_data.copy()
        updated_data["emails"] = failed_email_dicts
        updated_data["status"] = "pending"
        updated_data["updated_at"] = datetime.now().isoformat()
        return False, updated_data

    def run(self):
        """Main worker loop — owns the EmailSender for its entire lifetime."""
        self.running = True
        self.logger.info(f"Worker {self.worker_id} started")

        consecutive_failures = 0
        base_retry_delay = 5
        max_retry_delay = 60

        with EmailSender() as self.email_sender:
            while self.running:
                try:
                    batches = self.queue_manager.get_next_batch(max_batches=1)

                    if not batches:
                        time.sleep(base_retry_delay)
                        consecutive_failures = 0
                        continue

                    self.current_batch = batches[0]
                    success, updated_batch_data = self.process_batch(self.current_batch)

                    self.queue_manager.mark_batch_complete(
                        self.current_batch["file"],
                        successful=success,
                        updated_data=updated_batch_data,
                    )
                    self.current_batch = None
                    consecutive_failures = 0

                except json.JSONDecodeError as e:
                    consecutive_failures += 1
                    delay = min(base_retry_delay * (2 ** (consecutive_failures - 1)), max_retry_delay)
                    self.logger.error(
                        f"JSON error in worker {self.worker_id}: {e}. Retry in {delay}s"
                    )
                    time.sleep(delay)

                except Exception as e:
                    consecutive_failures += 1
                    delay = min(base_retry_delay * (2 ** (consecutive_failures - 1)), max_retry_delay)
                    self.logger.error(
                        f"Error in worker {self.worker_id}: {e}. Retry in {delay}s "
                        f"(failure #{consecutive_failures})"
                    )
                    time.sleep(delay)

                    if consecutive_failures >= 3:
                        self.logger.warning(
                            f"Worker {self.worker_id}: {consecutive_failures} consecutive failures, "
                            f"extended break of {max_retry_delay}s"
                        )
                        time.sleep(max_retry_delay)
                        consecutive_failures = 0

    def stop(self):
        self.running = False
        self.logger.info(f"Worker {self.worker_id} stopped")


class WorkerPool:
    """Manages a pool of email workers."""

    def __init__(self, queue_manager: QueueManager, num_workers: int = 3):
        self.queue_manager = queue_manager
        self.num_workers = num_workers
        self.workers: list[EmailWorker] = []
        self.threads: list[threading.Thread] = []
        self.logger = setup_logger("WorkerPool", "logs/worker_pool.log")
        Path("logs").mkdir(exist_ok=True)

    def start(self):
        self.logger.info(f"Starting worker pool with {self.num_workers} workers")
        for i in range(self.num_workers):
            worker = EmailWorker(i + 1, self.queue_manager)
            thread = threading.Thread(target=worker.run, daemon=True)
            self.workers.append(worker)
            self.threads.append(thread)
            thread.start()
            self.logger.debug(f"Started worker {i + 1}")

    def stop(self):
        self.logger.info("Stopping worker pool")
        for worker in self.workers:
            worker.stop()
        for thread in self.threads:
            thread.join(timeout=5)
        self.logger.info("Worker pool stopped")

    def get_status(self) -> dict:
        status = {
            "total_workers": len(self.workers),
            "active_workers": 0,
            "workers": [],
        }
        for worker in self.workers:
            status["workers"].append({
                "worker_id": worker.worker_id,
                "running": worker.running,
                "current_batch": (
                    worker.current_batch["file"].name if worker.current_batch else None
                ),
                "emails_sent": worker.emails_sent,
                "emails_failed": worker.emails_failed,
                "avg_latency_ms": round(worker.avg_latency_ms, 2),
            })
            if worker.running:
                status["active_workers"] += 1
        return status


class BatchProcessor:
    """Standalone batch processor for manual/testing use."""

    def __init__(self, queue_manager: QueueManager):
        self.queue_manager = queue_manager
        self.logger = setup_logger("BatchProcessor", "logs/batch_processor.log")

    def process_single_batch(self) -> bool:
        batches = self.queue_manager.get_next_batch(max_batches=1)
        if not batches:
            self.logger.info("No batches available")
            return False

        batch_data = batches[0]
        self.logger.info(f"Processing batch {batch_data['file'].name}")

        worker = EmailWorker(0, self.queue_manager)
        with EmailSender() as worker.email_sender:
            success, updated_batch_data = worker.process_batch(batch_data)

        self.queue_manager.mark_batch_complete(
            batch_data["file"],
            successful=success,
            updated_data=updated_batch_data,
        )
        return True
