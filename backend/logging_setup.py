import logging
import os
import re
from logging.handlers import RotatingFileHandler

from backend.config import settings

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False

# API keys travel in query strings (SerpAPI ?api_key=, Google ?key=...). httpx
# logs full request URLs at INFO, which once leaked live keys into a committed
# log file. Redact them wherever they appear.
_SECRET_QS = re.compile(
    r"(?i)([?&](?:api[_-]?key|apikey|key|token|access_token|client_secret|secret|password)=)[^&\s\"']+"
)


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = _SECRET_QS.sub(r"\1[REDACTED]", message)
        if redacted != message:
            record.msg, record.args = redacted, ()
        return True


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    log_dir = settings.log_dir
    os.makedirs(log_dir, exist_ok=True)

    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "app.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))

    for handler in (file_handler, console_handler):
        handler.addFilter(RedactSecretsFilter())

    root.addHandler(file_handler)
    root.addHandler(console_handler)

    # Per-request URL logging from the HTTP stack is noise and a leak risk.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.handlers = [file_handler, console_handler]
    logging.getLogger("uvicorn.access").disabled = True

    logging.getLogger("__main__").info("Logging initialized: level=%s dir=%s", settings.log_level, log_dir)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
