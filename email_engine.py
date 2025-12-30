import smtplib
import ssl
from config import settings
from logger_engine import setup_logger
class Email:
    def send_email(subject,body,to_email):
        smtp_server = f"{settings.SMTP_SERVER}"
        port = settings.PORT
        sender_email = f"{settings.SENDER_EMAIL}"
        password = f"{settings.PASSWORD}"
    #Credentials
        import os
        BASE_DIR_LOG = os.getcwd()
        logger = setup_logger(__name__, f"{BASE_DIR_LOG}/log//email_engine.log")
    #Create secure ssl context
        context=ssl.create_default_context()
        logger.info("Connecting to SMTP")
        server = smtplib.SMTP_SSL(smtp_server,port)

        try:
            logger.info("Connection established")
            server.ehlo()
            server.login(sender_email,password)
        
            headers=f"From:{sender_email}\nSubject:{subject}\n"
            logger.info(f"Sending email to: {to_email}")
            server.sendmail(sender_email,to_email,headers+body)
        
        except Exception as e:
            logger.error(f"Failed to Connect:{e}")
        finally:
            server.quit()
        