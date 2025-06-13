# logging_config.py
import logging
import json
from datetime import datetime
from typing import Any, Dict

class StructuredLogger:
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        
        formatter = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}'
        )
        
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
    
    def log_event(self, event: str, data: Dict[str, Any], level: str = "INFO"):
        log_data = {
            "event": event,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data
        }
        msg = json.dumps(log_data)
        if level == "ERROR":
            self.logger.error(msg)
        elif level == "WARNING":
            self.logger.warning(msg)
        else:
            self.logger.info(msg)
