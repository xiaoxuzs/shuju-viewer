"""Logging configuration using stdlib + rich."""

from __future__ import annotations

import logging

from rich.logging import RichHandler

from app.core.config import settings


def configure_logging() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
