import smtplib
import ssl
import time
import threading
from email import utils as email_utils
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

from config import settings
from logger_engine import setup_logger


class EmailPriority(Enum):
    HIGH = 1
    NORMAL = 2
    LOW = 3


class EmailFormat(Enum):
    PLAIN = "plain"
    HTML = "html"
    MULTIPART = "multipart"


@dataclass
class EmailMessage:
    """Represents an email message with support for multiple formats."""
    subject: str
    body: str
    to_email: str
    from_email: Optional[str] = None
    cc: List[str] = None
    bcc: List[str] = None
    format: EmailFormat = EmailFormat.PLAIN
    html_body: Optional[str] = None
    attachments: List[Dict[str, Any]] = None
    priority: EmailPriority = EmailPriority.NORMAL

    def __post_init__(self):
        if self.from_email is None:
            self.from_email = settings.SENDER_EMAIL
        if self.cc is None:
            self.cc = []
        if self.bcc is None:
            self.bcc = []
        if self.attachments is None:
            self.attachments = []

    def to_mime_message(self) -> MIMEMultipart:
        """Convert to MIME message for sending."""
        if self.format == EmailFormat.MULTIPART:
            msg = MIMEMultipart('alternative')
        else:
            msg = MIMEMultipart()

        msg['Subject'] = self.subject
        msg['From'] = self.from_email
        msg['To'] = self.to_email
        msg['Message-ID'] = email_utils.make_msgid()

        if self.cc:
            msg['Cc'] = ', '.join(self.cc)

        if self.format == EmailFormat.PLAIN:
            msg.attach(MIMEText(self.body, 'plain', 'utf-8'))
        elif self.format == EmailFormat.HTML:
            msg.attach(MIMEText(self.body, 'html', 'utf-8'))
        elif self.format == EmailFormat.MULTIPART:
            msg.attach(MIMEText(self.body, 'plain', 'utf-8'))
            msg.attach(MIMEText(self.html_body if self.html_body else self.body, 'html', 'utf-8'))

        for attachment in self.attachments:
            part = MIMEApplication(attachment['data'], Name=attachment['filename'])
            part['Content-Disposition'] = f'attachment; filename="{attachment["filename"]}"'
            msg.attach(part)

        return msg


class EmailSender:
    """Email sender with retry logic, a thread-safe connection pool, and context-manager support."""

    def __init__(self, max_retries: int = 3, retry_delay: float = 1.0):
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.logger = setup_logger(__name__, "logs/email_sender.log")
        self._connection_pool: Dict[tuple, smtplib.SMTP_SSL] = {}
        self._pool_lock = threading.RLock()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._close_all_connections()

    def _get_connection(self, smtp_server: str, port: int) -> smtplib.SMTP_SSL:
        with self._pool_lock:
            key = (smtp_server, port)
            if key in self._connection_pool:
                conn = self._connection_pool[key]
                try:
                    conn.noop()
                    return conn
                except Exception:
                    del self._connection_pool[key]

            context = ssl.create_default_context()
            conn = smtplib.SMTP_SSL(smtp_server, port, context=context, timeout=30)
            conn.ehlo()
            conn.login(settings.SENDER_EMAIL, settings.PASSWORD)
            self._connection_pool[key] = conn
            return conn

    def _close_all_connections(self):
        with self._pool_lock:
            for conn in self._connection_pool.values():
                try:
                    conn.quit()
                except Exception:
                    pass
            self._connection_pool.clear()

    def send_email(self, email_message: EmailMessage) -> bool:
        smtp_server = settings.SMTP_SERVER
        port = settings.PORT
        sender_email = email_message.from_email or settings.SENDER_EMAIL
        recipients = [email_message.to_email] + email_message.cc + email_message.bcc

        for attempt in range(self.max_retries):
            try:
                self.logger.info(
                    f"Attempt {attempt + 1}/{self.max_retries} sending to {email_message.to_email}"
                )
                conn = self._get_connection(smtp_server, port)
                conn.sendmail(sender_email, recipients, email_message.to_mime_message().as_string())
                self.logger.info(f"Sent to {email_message.to_email}")
                return True

            except Exception as e:
                self.logger.error(f"Send failed (attempt {attempt + 1}): {e}")
                key = (smtp_server, port)
                with self._pool_lock:
                    if key in self._connection_pool:
                        try:
                            self._connection_pool[key].quit()
                        except Exception:
                            pass
                        del self._connection_pool[key]

                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (2 ** attempt)
                    self.logger.info(f"Retrying in {delay:.1f}s...")
                    time.sleep(delay)
                else:
                    self.logger.error(f"Max retries exceeded for {email_message.to_email}")
                    return False

        return False

    def send_batch(self, email_messages: List[EmailMessage]) -> Dict[str, Any]:
        results: Dict[str, Any] = {
            "total": len(email_messages),
            "successful": 0,
            "failed": 0,
            "details": [],
        }
        for email_msg in email_messages:
            success = self.send_email(email_msg)
            if success:
                results["successful"] += 1
                results["details"].append({"to": email_msg.to_email, "status": "success"})
            else:
                results["failed"] += 1
                results["details"].append({"to": email_msg.to_email, "status": "failed"})
        self.logger.info(
            f"Batch complete: {results['successful']} sent, {results['failed']} failed"
        )
        return results


def send_simple_email(subject: str, body: str, to_email: str, format: str = "plain") -> bool:
    """Backward-compatible helper for one-shot sends."""
    format_map = {"html": EmailFormat.HTML, "multipart": EmailFormat.MULTIPART}
    email_msg = EmailMessage(
        subject=subject,
        body=body,
        to_email=to_email,
        format=format_map.get(format, EmailFormat.PLAIN),
    )
    with EmailSender() as sender:
        return sender.send_email(email_msg)
