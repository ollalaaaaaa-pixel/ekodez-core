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
) -> str:
    if deploying():
        state.failures = 0
        save(state)
        return "deploy_skip"
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
