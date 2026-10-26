"""Application logger: stdout (captured by supervisord) plus a rotating file in the data dir."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from mods.config import Config


def setup_logger(name: str = "echoradio", level: int = logging.INFO) -> logging.Logger:
    log = logging.getLogger(name)
    if log.handlers:
        return log
    log.setLevel(level)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    log.addHandler(console)
    try:
        os.makedirs(Config.LOGS_ROOT, exist_ok=True)
        fh = RotatingFileHandler(os.path.join(Config.LOGS_ROOT, "echoradio.log"),
                                 maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except OSError:
        pass
    return log


logger = setup_logger()
