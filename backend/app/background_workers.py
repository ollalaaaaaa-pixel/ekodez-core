"""Application-owned workers: signal everyone before waiting for any worker."""

import threading
import time
from collections.abc import Callable
from typing import Protocol


class Worker(Protocol):
    stop_event: threading.Event
    thread: threading.Thread

    def start(self) -> None: ...


class ThreadWorker:
    def __init__(self, name: str, target: Callable[[threading.Event], None]):
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=target, args=(self.stop_event,), name=name, daemon=True
        )

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

    def shutdown(self, timeout: float = 20.0) -> None:
        for worker in self.workers:
            worker.stop_event.set()
        deadline = time.monotonic() + timeout
        for worker in self.workers:
            if worker.thread.ident is not None:
                worker.thread.join(max(0.0, deadline - time.monotonic()))
        remaining = [w.thread.name for w in self.workers if w.thread.is_alive()]
        if remaining:
            raise RuntimeError(
                "Background worker shutdown timed out: " + ", ".join(remaining)
            )
        self.workers.clear()
