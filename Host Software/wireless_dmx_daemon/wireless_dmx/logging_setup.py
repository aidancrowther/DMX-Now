"""Structured application logging."""

from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> logging.Logger:
    numeric = getattr(logging, level.upper(), None)
    if not isinstance(numeric, int):
        raise ValueError(f"unknown log level: {level}")
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)s %(name)s event=%(message)s",
        stream=sys.stderr,
    )
    return logging.getLogger("wireless_dmx")