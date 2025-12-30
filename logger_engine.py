import logging
import sys
import os
from logging.handlers import RotatingFileHandler

def setup_logger(name, log_file_path='app.log'):
    """Create and configure a logger with file rotation
    
    Args:
        name (str): Logger name (usually __name__)
        log_file_path (str): Custom path for log file
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)  # Capture all levels

    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s | %(name)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Ensure directory exists for log file
    log_directory = os.path.dirname(log_file_path)
    if log_directory:  # Only create if path contains directories
        os.makedirs(log_directory, exist_ok=True)

    # Create rotating file handler with specified path
    file_handler = RotatingFileHandler(
        filename=log_file_path,
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Add handlers
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger




# logger.debug("Starting data processing")
#     try:
#         logger.info("Processing 100 records")
#         # ... your code ...
#         logger.warning("Temporary file storage approaching limit")
#         # ... your code ...
#     except Exception as e:
#         logger.error(f"Processing failed: {str(e)}", exc_info=True)
