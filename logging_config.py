import logging
import json
import os
from datetime import datetime
from typing import Any, Dict
from logging.handlers import TimedRotatingFileHandler

class ExactLevelFilter(logging.Filter):
    def __init__(self, level: int):
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == self.level

class StructuredLogger:
    def __init__(self, name: str):
        os.makedirs("logs", exist_ok=True)
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG if os.getenv("ENV") == "dev" else logging.INFO)
        self.logger.propagate = False

        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": %(message)s}'
        )

        if self.logger.hasHandlers():
            self.logger.handlers.clear()
            
        # Stream (console) handler
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        self.logger.addHandler(stream_handler)

        # app.log — DEBUG + INFO (rotated daily)
        app_handler = TimedRotatingFileHandler("logs/app.log", when="midnight", interval=1, backupCount=7, encoding="utf-8")
        app_handler.setFormatter(formatter)
        app_handler.setLevel(logging.DEBUG)
        app_handler.addFilter(lambda record: record.levelno < logging.WARNING)
        self.logger.addHandler(app_handler)

        # warning.log — only WARNING (daily)
        warning_handler = TimedRotatingFileHandler("logs/warning.log", when="midnight", interval=1, backupCount=7, encoding="utf-8")
        warning_handler.setFormatter(formatter)
        warning_handler.setLevel(logging.WARNING)
        warning_handler.addFilter(ExactLevelFilter(logging.WARNING))
        self.logger.addHandler(warning_handler)

        # error.log — ERROR & CRITICAL (daily)
        error_handler = TimedRotatingFileHandler("logs/error.log", when="midnight", interval=1, backupCount=7, encoding="utf-8")
        error_handler.setFormatter(formatter)
        error_handler.setLevel(logging.ERROR)
        self.logger.addHandler(error_handler)

    def log_event(self, event: str, data: Dict[str, Any], level: str = "INFO"):
        log_data = {
            "event": event,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data
        }
        msg = json.dumps(log_data)

        level = level.upper()
        if level == "ERROR":
            self.logger.error(msg)
        elif level == "WARNING":
            self.logger.warning(msg)
        elif level == "DEBUG":
            self.logger.debug(msg)
        else:
            self.logger.info(msg)
