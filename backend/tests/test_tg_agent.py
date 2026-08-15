import json
import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app import tg_poller
from app.models import Base, Transaction


class FakeResponse:
    def __init__(self, value, *, raw=False):
        self.value = value
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        if self.raw:
            return self.value
        return json.dumps(self.value).encode("utf-8")


class StopLoop(BaseException):
    pass


class TelegramAgentTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_parses_direction_decimal_amount_and_category(self):
        cases = {
            "купил химию за 3500": (
                "expense",
                Decimal("3500"),
                "Материалы",
            ),
            "потратил 1 250,50 на бензин": (
                "expense",
                Decimal("1250.50"),
                "Топливо и машина",
            ),
            "оплатил аренду 9000": (
                "expense",
                Decimal("9000"),
                "Другое",
            ),
            "получил 5000 за дезинфекцию": (
                "income",
                Decimal("5000"),
                "Дезинфекция",
            ),
            "перевели нам 7000 за дератизацию": (
                "income",
                Decimal("7000"),
                "Другие работы",
            ),
            "оплатили нам 4200 за насекомых": (
                "income",
                Decimal("4200"),
                "Другие работы",
            ),
            "непонятная операция": (
                "unknown",
                Decimal("0.00"),
                "Другое",
            ),
        }

        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(tg_poller._parse_agent_text(text), expected)

    def test_whitelist_uses_only_numeric_configured_ids(self):
        with patch.dict(
            os.environ,
            {"OWNER_TG_ID": "101", "ALEXEY_TG_ID": "202"},
            clear=False,
        ):
            self.assertEqual(tg_poller._allowed_sender_ids(), {101, 202})

    def test_whoami_replies_with_numeric_chat_id(self):
        payload = {
            "ok": True,
            "result": [
                {
                    "update_id": 501,
                    "message": {
                        "from": {"id": 303},
                        "chat": {"id": 303, "type": "private"},
                        "text": "/whoami",
                    },
                }
            ],
        }

        with (
            patch.object(tg_poller, "_load_offset", return_value=0),
            patch.object(tg_poller, "_save_offset"),
            patch.object(tg_poller, "_send_message") as send_message,
            patch.object(
                tg_poller.urllib.request,
                "urlopen",
                return_value=FakeResponse(payload),
            ),
            patch.object(tg_poller.time, "sleep", side_effect=StopLoop),
            self.assertRaises(StopLoop),
        ):
            tg_poller._loop("token", self.engine)

        send_message.assert_called_once_with("token", 303, "303")

    def test_loop_routes_whitelisted_private_text_to_agent(self):
        message = {
            "from": {"id": 101},
            "chat": {"id": 101, "type": "private"},
            "text": "купил химию за 3500",
        }
        payload = {"ok": True, "result": [{"update_id": 502, "message": message}]}

        with (
            patch.dict(os.environ, {"OWNER_TG_ID": "101"}, clear=False),
            patch.object(tg_poller, "_load_offset", return_value=0),
            patch.object(tg_poller, "_save_offset"),
            patch.object(tg_poller, "_handle_agent_message") as handle,
            patch.object(
                tg_poller.urllib.request,
                "urlopen",
                return_value=FakeResponse(payload),
            ),
            patch.object(tg_poller.time, "sleep", side_effect=StopLoop),
            self.assertRaises(StopLoop),
        ):
            tg_poller._loop("token", self.engine)

        handle.assert_called_once_with("token", self.engine, message)

    def test_loop_routes_whitelisted_private_photo_without_text(self):
        message = {
            "from": {"id": 101},
            "chat": {"id": 101, "type": "private"},
            "photo": [{"file_id": "photo-id"}],
        }
        payload = {"ok": True, "result": [{"update_id": 503, "message": message}]}

        with (
            patch.dict(os.environ, {"OWNER_TG_ID": "101"}, clear=False),
            patch.object(tg_poller, "_load_offset", return_value=0),
            patch.object(tg_poller, "_save_offset"),
            patch.object(tg_poller, "_handle_agent_message") as handle,
            patch.object(
                tg_poller.urllib.request,
                "urlopen",
                return_value=FakeResponse(payload),
            ),
            patch.object(tg_poller.time, "sleep", side_effect=StopLoop),
            self.assertRaises(StopLoop),
        ):
            tg_poller._loop("token", self.engine)

        handle.assert_called_once_with("token", self.engine, message)

    def test_text_message_creates_review_draft_and_confirmation_card(self):
        message = {
            "from": {"id": 101},
            "chat": {"id": 101, "type": "private"},
            "text": "купил химию за 3500",
        }

        with patch.object(tg_poller, "_send_message") as send_message:
            tg_poller._handle_agent_message("token", self.engine, message)

        with Session(self.engine) as session:
            row = session.scalar(select(Transaction))
            self.assertIsNotNone(row)
            self.assertEqual(row.source, "tg_agent")
            self.assertEqual(row.operation_date, date.today())
            self.assertEqual(row.kind, "expense")
            self.assertEqual(row.amount, Decimal("3500.00"))
            self.assertEqual(row.category, "Материалы")
            self.assertTrue(row.review_required)
            tx_id = row.id

        send_message.assert_called_once_with(
            "token",
            101,
            "Черновик: расход 3500 Материалы",
            reply_markup={
                "inline_keyboard": [
                    [
                        {"text": "Подтвердить", "callback_data": f"ok:{tx_id}"},
                        {"text": "Отклонить", "callback_data": f"no:{tx_id}"},
                    ]
                ]
            },
        )

    def test_photo_downloads_and_creates_zero_draft_without_buttons(self):
        message = {
            "from": {"id": 101},
            "chat": {"id": 101, "type": "private"},
            "caption": "чек на материалы",
            "photo": [{"file_id": "small"}, {"file_id": "large_file"}],
        }

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            patch.object(tg_poller, "ATTACHMENTS_DIR", temp_dir),
            patch.object(
                tg_poller.urllib.request,
                "urlopen",
                side_effect=[
                    FakeResponse(
                        {"ok": True, "result": {"file_path": "photos/a.jpg"}}
                    ),
                    FakeResponse(b"synthetic-image", raw=True),
                ],
            ),
            patch.object(tg_poller, "_send_message") as send_message,
        ):
            tg_poller._handle_agent_message("token", self.engine, message)

            files = os.listdir(temp_dir)
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].endswith("_large_file.jpg"))

        with Session(self.engine) as session:
            row = session.scalar(select(Transaction))
            self.assertEqual(row.amount, Decimal("0.00"))
            self.assertEqual(row.kind, "unknown")
            self.assertEqual(row.category, "Другое")
            self.assertTrue(row.review_required)
            self.assertIn("фото:", row.description)
            self.assertIn("чек на материалы", row.description)

        send_message.assert_called_once_with(
            "token",
            101,
            "Фото принято, черновик в пульте на проверке",
        )

    def test_voice_or_other_message_requests_text_duplicate(self):
        message = {
            "from": {"id": 101},
            "chat": {"id": 101, "type": "private"},
            "voice": {"file_id": "voice"},
        }

        with patch.object(tg_poller, "_send_message") as send_message:
            tg_poller._handle_agent_message("token", self.engine, message)

        send_message.assert_called_once_with(
            "token",
            101,
            "Голосовые пока продублируйте текстом (распознавание — в следующей версии)",
        )
        with Session(self.engine) as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(Transaction)),
                0,
            )

    def make_draft(self) -> int:
        with Session(self.engine) as session:
            row = Transaction(
                source="tg_agent",
                operation_date=date.today(),
                amount=Decimal("3500.00"),
                category="Материалы",
                description="синтетический черновик",
                kind="expense",
                review_required=True,
            )
            session.add(row)
            session.commit()
            return row.id

    def callback(self, action: str, tx_id: int) -> dict:
        return {
            "id": "callback-1",
            "from": {"id": 101},
            "data": f"{action}:{tx_id}",
            "message": {"message_id": 55, "chat": {"id": 101}},
        }

    def test_ok_callback_confirms_draft_and_keeps_kind(self):
        tx_id = self.make_draft()

        with (
            patch.object(tg_poller, "_answer_callback_query") as answer,
            patch.object(tg_poller, "_edit_message") as edit,
        ):
            tg_poller._handle_callback(
                "token",
                self.engine,
                self.callback("ok", tx_id),
                {101},
            )

        with Session(self.engine) as session:
            row = session.get(Transaction, tx_id)
            self.assertFalse(row.review_required)
            self.assertEqual(row.kind, "expense")
        answer.assert_called_once_with("token", "callback-1")
        edit.assert_called_once_with("token", 101, 55, "✅ Проведено")

    def test_no_callback_deletes_draft(self):
        tx_id = self.make_draft()

        with (
            patch.object(tg_poller, "_answer_callback_query") as answer,
            patch.object(tg_poller, "_edit_message") as edit,
        ):
            tg_poller._handle_callback(
                "token",
                self.engine,
                self.callback("no", tx_id),
                {101},
            )

        with Session(self.engine) as session:
            self.assertIsNone(session.get(Transaction, tx_id))
        answer.assert_called_once_with("token", "callback-1")
        edit.assert_called_once_with("token", 101, 55, "❌ Отклонено")


if __name__ == "__main__":
    unittest.main()
