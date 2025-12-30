import smtplib
import ssl
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from typing import Optional, List, Dict, Any, Union
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

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
        
        if self.cc:
            msg['Cc'] = ', '.join(self.cc)
        if self.bcc:
            # BCC is not included in headers to hide recipients
            pass
        
        # Add body parts
        if self.format == EmailFormat.PLAIN:
            msg.attach(MIMEText(self.body, 'plain', 'utf-8'))
        elif self.format == EmailFormat.HTML:
            msg.attach(MIMEText(self.body, 'html', 'utf-8'))
        elif self.format == EmailFormat.MULTIPART:
            # Add both plain and HTML versions
            if self.html_body:
                msg.attach(MIMEText(self.body, 'plain', 'utf-8'))
                msg.attach(MIMEText(self.html_body, 'html', 'utf-8'))
            else:
                # If no HTML body provided, use the same body for both
                msg.attach(MIMEText(self.body, 'plain', 'utf-8'))
                msg.attach(MIMEText(self.body, 'html', 'utf-8'))
        
        # Add attachments
        for attachment in self.attachments:
            part = MIMEApplication(
                attachment['data'],
                Name=attachment['filename']
            )
            part['Content-Disposition'] = f'attachment; filename="{attachment["filename"]}"'
            msg.attach(part)
        
        return msg

class EmailSender:
    """Enhanced email sender with retry logic and connection pooling."""
    
    def __init__(self, max_retries: int = 3, retry_delay: float = 1.0):
        """
        Initialize the email sender.
        
        Args:
            max_retries: Maximum number of retry attempts
            retry_delay: Base delay between retries (exponential backoff)
        """
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.logger = setup_logger(__name__, "logs/email_sender.log")
        self._connection_pool = {}
    
    def _get_connection(self, smtp_server: str, port: int) -> smtplib.SMTP_SSL:
        """
        Get a connection from the pool or create a new one.
        
        Args:
            smtp_server: SMTP server address
            port: SMTP port
            
        Returns:
            SMTP_SSL connection
        """
        key = (smtp_server, port)
        
        if key in self._connection_pool:
            conn = self._connection_pool[key]
            try:
                # Test connection
                conn.noop()
                return conn
            except:
                # Connection is dead, remove from pool
                del self._connection_pool[key]
        
        # Create new connection
        context = ssl.create_default_context()
        conn = smtplib.SMTP_SSL(smtp_server, port, context=context)
        conn.ehlo()
        conn.login(settings.SENDER_EMAIL, settings.PASSWORD)
        
        # Add to pool
        self._connection_pool[key] = conn
        return conn
    
    def _close_all_connections(self):
        """Close all connections in the pool."""
        for key, conn in list(self._connection_pool.items()):
            try:
                conn.quit()
            except:
                pass
            del self._connection_pool[key]
    
    def send_email(self, email_message: EmailMessage) -> bool:
        """
        Send an email with retry logic.
        
        Args:
            email_message: EmailMessage object to send
            
        Returns:
            True if sent successfully, False otherwise
        """
        smtp_server = settings.SMTP_SERVER
        port = settings.PORT
        sender_email = email_message.from_email or settings.SENDER_EMAIL
        password = settings.PASSWORD
        
        # Prepare recipients
        recipients = [email_message.to_email] + email_message.cc + email_message.bcc
        
        for attempt in range(self.max_retries):
            try:
                self.logger.info(f"Attempt {attempt + 1}/{self.max_retries} to send email to {email_message.to_email}")
                
                # Get connection from pool
                conn = self._get_connection(smtp_server, port)
                
                # Convert to MIME message
                mime_msg = email_message.to_mime_message()
                
                # Send email
                conn.sendmail(
                    sender_email,
                    recipients,
                    mime_msg.as_string()
                )
                
                self.logger.info(f"Successfully sent email to {email_message.to_email}")
                return True
                
            except Exception as e:
                self.logger.error(f"Failed to send email (attempt {attempt + 1}): {e}")
                
                # Close the failed connection
                key = (smtp_server, port)
                if key in self._connection_pool:
                    try:
                        self._connection_pool[key].quit()
                    except:
                        pass
                    del self._connection_pool[key]
                
                # Check if we should retry
                if attempt < self.max_retries - 1:
                    # Exponential backoff
                    delay = self.retry_delay * (2 ** attempt)
                    self.logger.info(f"Retrying in {delay:.1f} seconds...")
                    time.sleep(delay)
                else:
                    self.logger.error(f"Max retries exceeded for email to {email_message.to_email}")
                    return False
        
        return False
    
    def send_batch(self, email_messages: List[EmailMessage]) -> Dict[str, Any]:
        """
        Send a batch of emails.
        
        Args:
            email_messages: List of EmailMessage objects
            
        Returns:
            Dictionary with results
        """
        results = {
            "total": len(email_messages),
            "successful": 0,
            "failed": 0,
            "details": []
        }
        
        for email_msg in email_messages:
            success = self.send_email(email_msg)
            
            if success:
                results["successful"] += 1
                results["details"].append({
                    "to": email_msg.to_email,
                    "status": "success"
                })
            else:
                results["failed"] += 1
                results["details"].append({
                    "to": email_msg.to_email,
                    "status": "failed"
                })
        
        self.logger.info(f"Batch send complete: {results['successful']} successful, {results['failed']} failed")
        return results
    
    def __del__(self):
        """Cleanup connections when object is destroyed."""
        self._close_all_connections()

# Helper functions for backward compatibility
def send_simple_email(subject: str, body: str, to_email: str, format: str = "plain") -> bool:
    """
    Simple function to send an email (backward compatible with old email_engine.py).
    
    Args:
        subject: Email subject
        body: Email body
        to_email: Recipient email address
        format: Email format ('plain', 'html', or 'multipart')
        
    Returns:
        True if sent successfully, False otherwise
    """
    # Convert format string to Enum
    if format == "html":
        email_format = EmailFormat.HTML
    elif format == "multipart":
        email_format = EmailFormat.MULTIPART
    else:
        email_format = EmailFormat.PLAIN
    
    email_msg = EmailMessage(
        subject=subject,
        body=body,
        to_email=to_email,
        format=email_format
    )
    
    sender = EmailSender()
    return sender.send_email(email_msg)

# Example usage
if __name__ == "__main__":
    # Test with jamalnader@jamalnader.com
    print("Testing email sender...")
    
    # Test 1: Plain text email
    email1 = EmailMessage(
        subject="Test Plain Email",
        body="This is a plain text email.",
        to_email="jamalnader@jamalnader.com",
        format=EmailFormat.PLAIN
    )
    
    # Test 2: HTML email
    email2 = EmailMessage(
        subject="Test HTML Email",
        body="<h1>This is an HTML email</h1><p>With some content.</p>",
        to_email="jamalnader@jamalnader.com",
        format=EmailFormat.HTML
    )
    
    # Test 3: Multipart email
    email3 = EmailMessage(
        subject="Test Multipart Email",
        body="This is the plain text version.",
        html_body="<h1>This is the HTML version</h1><p>With more formatting.</p>",
        to_email="jamalnader@jamalnader.com",
        format=EmailFormat.MULTIPART
    )
    
    sender = EmailSender()
    
    # Send test emails (commented out to avoid actually sending during testing)
    # print("Sending test emails...")
    # result1 = sender.send_email(email1)
    # print(f"Plain email: {'Success' if result1 else 'Failed'}")
    # 
    # result2 = sender.send_email(email2)
    # print(f"HTML email: {'Success' if result2 else 'Failed'}")
    # 
    # result3 = sender.send_email(email3)
    # print(f"Multipart email: {'Success' if result3 else 'Failed'}")
    
    print("Test completed (emails not actually sent to avoid spam).")
