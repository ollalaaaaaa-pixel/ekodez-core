import argparse
import asyncio
import copy
import logging
from datetime import datetime
from pathlib import Path

import uvicorn
from uvicorn.config import LOGGING_CONFIG
from uvicorn.logging import AccessFormatter, DefaultFormatter


class IsoTimeMixin:
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return (
            datetime.fromtimestamp(record.created)
            .astimezone()
            .isoformat(timespec="milliseconds")
        )


class IsoAccessFormatter(IsoTimeMixin, AccessFormatter):
    pass


class IsoDefaultFormatter(IsoTimeMixin, DefaultFormatter):
    pass


def loop_factory() -> asyncio.SelectorEventLoop:
    # An explicit factory: Uvicorn's factory overrides global loop policies.
    return asyncio.SelectorEventLoop()


def create_config() -> uvicorn.Config:
    log_config = copy.deepcopy(LOGGING_CONFIG)
    for name, formatter in (
        ("access", "scripts.run_backend.IsoAccessFormatter"),
        ("default", "scripts.run_backend.IsoDefaultFormatter"),
    ):
        log_config["formatters"][name]["()"] = formatter
        log_config["formatters"][name]["fmt"] = (
            "%(asctime)s " + log_config["formatters"][name]["fmt"]
        )
        log_config["formatters"][name]["use_colors"] = False
    return uvicorn.Config(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        proxy_headers=False,
        loop="scripts.run_backend:loop_factory",
        limit_concurrency=200,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=20,
        log_config=log_config,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance-root", type=Path)
    args = parser.parse_args()
    if (
        args.instance_root
        and args.instance_root.resolve() != Path(__file__).resolve().parents[1]
    ):
        parser.error("instance-root does not match backend directory")
    uvicorn.Server(create_config()).run()


if __name__ == "__main__":
    main()
