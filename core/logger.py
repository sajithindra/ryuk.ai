import logging
import sys
from config import LOG_LEVEL, LOG_FILE

def setup_logger(name="ryuk"):
    logger = logging.getLogger(name)
    
    # Avoid duplicate handlers if setup multiple times
    if logger.handlers:
        return logger
        
    logger.setLevel(LOG_LEVEL)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler
    try:
        file_handler = logging.FileHandler(LOG_FILE)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Warning: Could not create log file {LOG_FILE}: {e}")
        
    return logger

# Singleton instance for general use
logger = setup_logger()
