from __future__ import annotations
import logging
import os

NAME = "bvb-esef"
ENV_VAR = "BVB_ESEF_LOGLEVEL"
DEFAULT_LEVEL = "INFO"

log = logging.getLogger(NAME)


def setup() -> logging.Logger:
    level = os.environ.get(ENV_VAR, DEFAULT_LEVEL).strip().upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        level = DEFAULT_LEVEL
    log.setLevel(level)
    if not log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        log.addHandler(handler)
    return log
