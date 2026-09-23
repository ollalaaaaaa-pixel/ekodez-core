"""Standalone health watchdog. No application imports or database access."""

import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

ALERT = "backend перезапущен watchdog: health fail x2"
LOG = logging.getLogger("backend_watchdog")
RESTART_LOCK_TIMEOUT_SECONDS = 600


@dataclass
class State:
    failures: int = 0
    cooldown_until: float = 0


def cycle(
    state: State,
    now: float,
    deploying: Callable[[], bool],
    probe: Callable[[], bool],
    restart: Callable[[], bool],
    notify: Callable[[str], bool],
    save: Callable[[State], None],
    lock_status: Callable[[], str] | None = None,
    clear_stale: Callable[[], bool] | None = None,
) -> str:
    if deploying():
        state.failures = 0
        save(state)
        return "deploy_skip"
    if lock_status is not None and lock_status() == "busy":
        state.failures = 0
        save(state)
        return "lock_busy"
    if now < state.cooldown_until:
        return "cooldown"
    healthy = probe()
    if healthy:
        state.failures = 0
        save(state)
        return "healthy"
    state.failures += 1
    save(state)
    if state.failures < 2:
        return "health_warning"
    if deploying():
        state.failures = 0
        save(state)
        return "deploy_skip"
    if lock_status is not None:
        status = lock_status()
        if status == "busy" or (
            status == "stale" and (clear_stale is None or not clear_stale())
        ):
            state.failures = 0
            save(state)
            return "lock_busy"
    # Persist BEFORE the mutation. A crash or failed recovery cannot cause a storm.
    state.failures = 0
    state.cooldown_until = now + 600
    save(state)
    try:
        recovered = restart()
    except Exception:
        recovered = False
    state.cooldown_until = max(state.cooldown_until, time.time() + 600)
    save(state)
    if not recovered:
        return "restart_failed"
    try:
        sent = notify(ALERT)
    except Exception:
        sent = False
    return "restarted" if sent else "restarted_alert_failed"


def restart_lock_status(
    path: Path, now: float, timeout: int = RESTART_LOCK_TIMEOUT_SECONDS
) -> str:
    try:
        age = now - path.stat().st_mtime
    except FileNotFoundError:
        return "free"
    return "stale" if age >= timeout else "busy"


def clear_stale_restart_lock(
    path: Path, now: float, timeout: int = RESTART_LOCK_TIMEOUT_SECONDS
) -> bool:
    if restart_lock_status(path, now, timeout) != "stale":
        return False
    stale = path.with_name(f"{path.name}.stale.{os.getpid()}.{time.time_ns()}")
    try:
        os.replace(path, stale)
        stale.unlink()
    except OSError:
        return False
    LOG.warning("%s event=stale_restart_lock", datetime.now().astimezone().isoformat())
    return True


def probe_health() -> bool:
    results = []
    # Ignore system proxy configuration for localhost probes.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for path in ("/health", "/health/db"):
        try:
            with opener.open("http://127.0.0.1:8000" + path, timeout=5) as response:
                body = json.loads(response.read(4096))
                results.append(response.status == 200 and body.get("status") == "ok")
        except Exception:
            results.append(False)
    return all(results)


def notify_owner(message: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    owner = os.getenv("OWNER_TG_ID", "")
    if not token or not owner.isdigit():
        return False
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps({"chat_id": owner, "text": message}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return bool(json.loads(response.read(4096)).get("ok"))
    except Exception:
        return False  # Never log URLs, exception messages or tokens.


def save_state(path: Path, state: State) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(state)), encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    import msvcrt

    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def main() -> None:
    from dotenv import load_dotenv

    backend = Path(__file__).resolve().parents[1]
    if backend.parent.name != "ekodez-core":
        raise SystemExit("Watchdog requires the deployed ekodez-core checkout")
    root = backend.parent.parent
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    logging.basicConfig(filename=logs / "backend-watchdog.log", level=logging.INFO)
    load_dotenv(backend / ".env", override=False)
    state_path = logs / "backend-watchdog-state.json"
    restart_lock = logs / "backend-restart.lock"
    try:
        with exclusive_lock(logs / "backend-watchdog.lock"):
            # Corrupt state fails closed; never guess away a cooldown.
            state = (
                State(**json.loads(state_path.read_text()))
                if state_path.exists()
                else State()
            )

            def restart() -> bool:
                result = subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(
                            backend.parent
                            / "deployment"
                            / "autostart"
                            / "restart-backend.ps1"
                        ),
                        "-Root",
                        str(root),
                        "-PythonExecutable",
                        str(Path(sys.base_prefix) / "python.exe"),
                    ],
                    capture_output=True,
                    timeout=90,
                    check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                return result.returncode == 0

            event = cycle(
                state,
                time.time(),
                (root / "deploy-in-progress").exists,
                probe_health,
                restart,
                notify_owner,
                lambda value: save_state(state_path, value),
                lambda: restart_lock_status(restart_lock, time.time()),
                lambda: clear_stale_restart_lock(restart_lock, time.time()),
            )
    except Exception:
        event = "watchdog_unavailable"
    level = (
        logging.INFO
        if event in {"healthy", "deploy_skip", "cooldown", "restarted"}
        else logging.WARNING
    )
    LOG.log(level, "%s event=%s", datetime.now().astimezone().isoformat(), event)


if __name__ == "__main__":
    main()
