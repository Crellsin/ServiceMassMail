from pydantic import BaseModel
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

class Settings(BaseModel):
    SENDER_EMAIL: str
    PASSWORD: str
    SMTP_SERVER: str
    PORT: int
    AUTO_PROCESSING_ENABLED: bool = True
    NUM_WORKERS: int = 3
    WORKER_POLLING_INTERVAL: int = 5  # seconds

# Create an instance of the Settings model
settings = Settings(
    SENDER_EMAIL=os.getenv("SENDER_EMAIL"),
    PASSWORD=os.getenv("PASSWORD"),
    SMTP_SERVER=os.getenv("SMTP_SERVER"),
    PORT=int(os.getenv("PORT")),
    AUTO_PROCESSING_ENABLED=os.getenv("AUTO_PROCESSING_ENABLED", "True").lower() == "true",
    NUM_WORKERS=int(os.getenv("NUM_WORKERS", "3")),
    WORKER_POLLING_INTERVAL=int(os.getenv("WORKER_POLLING_INTERVAL", "5")),
)
