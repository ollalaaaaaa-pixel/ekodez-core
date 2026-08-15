import json
import os
import sys
import threading
import time
import traceback
import urllib.request

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.lead_parser import parse_order_text
from app.models import Lead

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OFFSET_FILE = os.path.join(BASE_DIR, "tg_offset.json")


def _load_offset() -> int:
    try:
        with open(OFFSET_FILE, encoding="utf-8") as f:
            return int(json.load(f).get("offset", 0))
    except Exception:
        return 0


def _save_offset(value: int) -> None:
    try:
        with open(OFFSET_FILE, "w", encoding="utf-8") as f:
            json.dump({"offset": value}, f)
    except Exception:
        pass


def _ingest(engine, text: str) -> str | None:
    data = parse_order_text(text)
    if not data["external_id"]:
        return None
    with Session(engine) as session:
        existing = session.scalar(
            select(Lead).where(Lead.external_id == data["external_id"])
        )
        if existing is not None:
            return "duplicate"
        row = Lead(
            source="telegram",
            external_id=data["external_id"] or None,
            order_at=data["order_at"],
            client_name=data["client_name"] or None,
            phone=data["phone"] or None,
            address=data["address"] or None,
            area=data["area"] or None,
            reason=data["reason"] or None,
            comment=data["comment"] or None,
            amount_note=data["amount_note"] or None,
            contract=data["contract"] or None,
            partner=data["partner"] or None,
            status="new",
            raw_text=text,
        )
        session.add(row)
        session.commit()
        print(f"lead ingested: {data['external_id']}")
        return "created"


def _send_message(token: str, chat_id: int, text: str) -> bool:
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=15) as r:
                payload = json.loads(r.read().decode("utf-8"))
            if not payload.get("ok"):
                raise RuntimeError("Telegram sendMessage returned ok=false")
            return True
        except Exception as exc:
            print(
                "TG sendMessage failed: "
                f"{type(exc).__name__}, attempt {attempt}/3",
                file=sys.stderr,
            )
            if attempt < 3:
                time.sleep(3)
    return False


def _loop(token: str, engine) -> None:
    offset = _load_offset()
    while True:
        try:
            url = (
                "https://api.telegram.org/bot"
                + token
                + "/getUpdates?timeout=5&offset="
                + str(offset)
            )
            with urllib.request.urlopen(url, timeout=15) as r:
                payload = json.loads(r.read().decode("utf-8"))
            updates = payload.get("result", [])
            if updates:
                print(f"tg updates: {len(updates)}")
            for update in updates:
                offset = max(offset, update["update_id"] + 1)
                channel_post = update.get("channel_post")
                message = update.get("message")
                msg = channel_post or message or {}
                text = msg.get("text") or ""
                if "id сделки" in text.lower():
                    result = _ingest(engine, text)
                    if message is not None:
                        chat_id = (message.get("chat") or {}).get("id")
                        if chat_id is not None and result == "created":
                            data = parse_order_text(text)
                            client_name = data["client_name"] or "не указано"
                            address = data["address"] or "не указано"
                            reason = data["reason"] or "не указано"
                            confirmation = (
                                f"✅ Заявка принята: {client_name}, "
                                f"{address} ({reason})"
                            )
                            _send_message(token, chat_id, confirmation)
                        elif chat_id is not None and result == "duplicate":
                            _send_message(
                                token,
                                chat_id,
                                "ℹ️ Заявка уже в системе",
                            )
            _save_offset(offset)
        except Exception:
            traceback.print_exc()
            time.sleep(3)
        time.sleep(2)


def start_poller(engine) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("TG poller: token not set, skip")
        return
    thread = threading.Thread(target=_loop, args=(token, engine), daemon=True)
    thread.start()
    print("TG poller: started")
