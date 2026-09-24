"""Application-owned workers: signal everyone before waiting for any worker."""

import logging
import sys
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from typing import Protocol

LOG = logging.getLogger(__name__)


def write_log_safe(message: str, level: int = logging.INFO) -> None:
    try:
        LOG.log(level, "%s", message)
    except Exception:
        with suppress(Exception):
            print(message, file=sys.stderr)


class Worker(Protocol):
    stop_event: threading.Event
    thread: threading.Thread

    def start(self) -> None: ...


class ThreadWorker:
    def __init__(
        self,
        name: str,
        target: Callable[[], None],
        stop_event: threading.Event | None = None,
    ):
        self.stop_event = stop_event if stop_event is not None else threading.Event()
        self.thread = threading.Thread(target=target, name=name, daemon=True)

    def start(self) -> None:
        self.thread.start()


class WorkerRegistry:
    def __init__(self) -> None:
        self.workers: list[Worker] = []

    def register(self, worker: Worker) -> None:
        if not any(existing is worker for existing in self.workers):
            self.workers.append(worker)

    def start(self, worker: Worker) -> None:
        self.register(worker)
        worker.start()

    def shutdown(self, timeout: float = 20.0) -> dict[str, list[str]]:
        for worker in self.workers:
            worker.stop_event.set()
        deadline = time.monotonic() + timeout
        for worker in self.workers:
            if worker.thread.ident is not None:
                worker.thread.join(max(0.0, deadline - time.monotonic()))
        timed_out = [str(w.thread.name) for w in self.workers if w.thread.is_alive()]
        stopped = [str(w.thread.name) for w in self.workers if not w.thread.is_alive()]
        if timed_out:
            write_log_safe(
                "worker_shutdown timed_out=" + ",".join(timed_out), logging.WARNING
            )
        self.workers.clear()
        return {"stopped": stopped, "timed_out": timed_out}
