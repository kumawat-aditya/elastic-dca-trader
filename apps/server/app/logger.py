import logging
import sys
from app.config import settings

# Define the global log format
LOG_FORMAT = "[%(asctime)s][%(levelname)s] [%(name)s] - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Extract the log level from settings safely
try:
    log_level = getattr(logging, settings.LOG_LEVEL.upper())
except AttributeError:
    log_level = logging.INFO

# Configure the root logger
logging.basicConfig(
    level=log_level,
    format=LOG_FORMAT,
    datefmt=DATE_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

def get_logger(module_name: str) -> logging.Logger:
    """
    Returns a configured logger instance for a specific module.
    Usage: logger = get_logger(__name__)
    """
    return logging.getLogger(module_name)