"""Fail-closed, hot-read business-automation switch shared with the watchdog."""

import json
import logging
from pathlib import Path

CONFIG_PATH = Path(r"C:\D\Экодез\ads\config.json")
LOG = logging.getLogger(__name__)


def maintenance_enabled() -> bool:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return True
    # Only an explicit JSON false authorizes business automation. No truthy strings.
    return not (isinstance(config, dict) and config.get("maintenance_mode") is False)


def skip_business_work(worker: str) -> bool:
    if not maintenance_enabled():
        return False
    LOG.warning("worker=%s skipped due to maintenance mode", worker)
    return True
