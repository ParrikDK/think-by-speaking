"""Loguru configuration — console + rotating file sink at backend/logs/app.log."""
import sys

from loguru import logger

from .config import BACKEND_ROOT

LOG_DIR = BACKEND_ROOT / "logs"


def setup_logging(level: str = "INFO") -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logger.remove()
    logger.add(
        LOG_DIR / "app.log",
        rotation="10 MB",
        retention="7 days",
        compression="gz",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<7} | {name}:{function}:{line} | {message}",
        level=level,
        enqueue=True,
    )
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <level>{message}</level>",
        level=level,
        colorize=True,
    )
