import logging
import os
from datetime import datetime
from pathlib import Path

class Logger:
    """Logger con manejo de archivos y consola, implementado como singleton"""
    _instance = None
    _loggers = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.log_dir = Path("logs")
        self.log_dir.mkdir(exist_ok=True)
        self._initialized = True
    
    def get_logger(self, name):
        """Get or create a logger with the specified name."""
        if name in self._loggers:
            return self._loggers[name]
        
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        
        log_file = self.log_dir / f"{name}_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
        
        self._loggers[name] = logger
        return logger
    
    def debug(self, name, message):
        """Log debug message."""
        self.get_logger(name).debug(message)
    
    def info(self, name, message):
        """Log info message."""
        self.get_logger(name).info(message)
    
    def warning(self, name, message):
        """Log warning message."""
        self.get_logger(name).warning(message)
    
    def error(self, name, message):
        """Log error message."""
        self.get_logger(name).error(message)
    
    def critical(self, name, message):
        """Log critical message."""
        self.get_logger(name).critical(message)


logger_instance = Logger()
