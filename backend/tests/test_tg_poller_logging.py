import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app import main, tg_poller
from app.models import Base, Lead


class StopLoop(BaseException):
    pass


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class TelegramPollerLoggingTest(unittest.TestCase):
    def test_health_reports_process_local_poller_state(self):
        with (
            patch.object(tg_poller, "poller_started", return_value=True),
            patch.object(main, "poller_started", tg_poller.poller_started),
        ):
            self.assertEqual(main.health()["telegram"], "started")

    def test_start_poller_sets_started_state_after_thread_start(self):
        tg_poller._poller_started = False
        with (
            patch.dict(tg_poller.os.environ, {"TELEGRAM_BOT_TOKEN": "test-token"}),
            patch.object(tg_poller.threading, "Thread") as thread_class,
        ):
            tg_poller.start_poller(object())

        thread_class.return_value.start.assert_called_once_with()
        self.assertTrue(tg_poller.poller_started())

    def test_ingest_logs_external_id_after_successful_commit(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        output = io.StringIO()

        with redirect_stdout(output):
            result = tg_poller._ingest(engine, "id сделки: 999100")

        with Session(engine) as session:
            count = session.scalar(select(func.count()).select_from(Lead))
        self.assertEqual(count, 1)
        self.assertEqual(result, "created")
        self.assertIn("lead ingested: 999100", output.getvalue())

    def test_ingest_returns_duplicate_without_creating_second_lead(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)

        tg_poller._ingest(engine, "id сделки: 999101")
        result = tg_poller._ingest(engine, "id сделки: 999101")

        with Session(engine) as session:
            count = session.scalar(select(func.count()).select_from(Lead))
        self.assertEqual(count, 1)
        self.assertEqual(result, "duplicate")

    def test_ingest_returns_none_when_external_id_is_missing(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)

        result = tg_poller._ingest(engine, "Имя клиента: Без номера")

        with Session(engine) as session:
            count = session.scalar(select(func.count()).select_from(Lead))
        self.assertEqual(count, 0)
        self.assertIsNone(result)

    def test_send_message_posts_json_payload(self):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["content_type"] = request.get_header("Content-type")
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse({"ok": True, "result": {"message_id": 1}})

        with patch.object(tg_poller.urllib.request, "urlopen", fake_urlopen):
            result = tg_poller._send_message("test-token", 42, "✅ Заявка принята")

        self.assertTrue(result)
        self.assertEqual(
            captured,
            {
                "url": "https://api.telegram.org/bottest-token/sendMessage",
                "method": "POST",
                "content_type": "application/json",
                "payload": {"chat_id": 42, "text": "✅ Заявка принята"},
                "timeout": 15,
            },
        )

    def test_send_message_retries_after_failure(self):
        success = FakeResponse({"ok": True, "result": {"message_id": 1}})

        with (
            patch.object(
                tg_poller.urllib.request,
                "urlopen",
                side_effect=[OSError("temporary failure"), success],
            ) as urlopen,
            patch.object(tg_poller.time, "sleep") as sleep,
        ):
            result = tg_poller._send_message("test-token", 42, "test")

        self.assertTrue(result)
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(3)

    def test_loop_confirms_created_personal_message(self):
        text = (
            "id сделки: 999102\n"
            "Имя клиента: Иван\n"
            "Адрес: Архангельск, Троицкий 1\n"
            "Причина обращения: тараканы"
        )
        payload = {
            "ok": True,
            "result": [
                {
                    "update_id": 124,
                    "message": {"chat": {"id": 77}, "text": text},
                }
            ],
        }

        with (
            patch.object(tg_poller, "_load_offset", return_value=0),
            patch.object(tg_poller, "_save_offset"),
            patch.object(tg_poller, "_ingest", return_value="created"),
            patch.object(tg_poller, "_send_message") as send_message,
            patch.object(
                tg_poller.urllib.request,
                "urlopen",
                return_value=FakeResponse(payload),
            ),
            patch.object(tg_poller.time, "sleep", side_effect=StopLoop),
            self.assertRaises(StopLoop),
        ):
            tg_poller._loop("test-token", object())

        send_message.assert_called_once_with(
            "test-token",
            77,
            "✅ Заявка принята: Иван, Архангельск, Троицкий 1 (тараканы)",
        )

    def test_loop_confirms_duplicate_personal_message(self):
        payload = {
            "ok": True,
            "result": [
                {
                    "update_id": 125,
                    "message": {
                        "chat": {"id": 78},
                        "text": "id сделки: 999103",
                    },
                }
            ],
        }

        with (
            patch.object(tg_poller, "_load_offset", return_value=0),
            patch.object(tg_poller, "_save_offset"),
            patch.object(tg_poller, "_ingest", return_value="duplicate"),
            patch.object(tg_poller, "_send_message") as send_message,
            patch.object(
                tg_poller.urllib.request,
                "urlopen",
                return_value=FakeResponse(payload),
            ),
            patch.object(tg_poller.time, "sleep", side_effect=StopLoop),
            self.assertRaises(StopLoop),
        ):
            tg_poller._loop("test-token", object())

        send_message.assert_called_once_with(
            "test-token", 78, "ℹ️ Заявка уже в системе"
        )

    def test_loop_does_not_confirm_channel_post(self):
        payload = {
            "ok": True,
            "result": [
                {
                    "update_id": 126,
                    "channel_post": {
                        "chat": {"id": -100123},
                        "text": "id сделки: 999104",
                    },
                }
            ],
        }

        with (
            patch.object(tg_poller, "_load_offset", return_value=0),
            patch.object(tg_poller, "_save_offset"),
            patch.object(tg_poller, "_ingest", return_value="created"),
            patch.object(tg_poller, "_send_message") as send_message,
            patch.object(
                tg_poller.urllib.request,
                "urlopen",
                return_value=FakeResponse(payload),
            ),
            patch.object(tg_poller.time, "sleep", side_effect=StopLoop),
            self.assertRaises(StopLoop),
        ):
            tg_poller._loop("test-token", object())

        send_message.assert_not_called()

    def test_loop_logs_nonempty_update_count(self):
        payload = {
            "ok": True,
            "result": [
                {
                    "update_id": 123,
                    "message": {"text": "обычное сообщение"},
                }
            ],
        }
        output = io.StringIO()

        with (
            patch.object(tg_poller, "_load_offset", return_value=0),
            patch.object(tg_poller, "_save_offset"),
            patch.object(
                tg_poller.urllib.request,
                "urlopen",
                return_value=FakeResponse(payload),
            ),
            patch.object(tg_poller.time, "sleep", side_effect=StopLoop),
            redirect_stdout(output),
            self.assertRaises(StopLoop),
        ):
            tg_poller._loop("test-token", object())

        self.assertIn("tg updates: 1", output.getvalue())

    def test_loop_prints_network_traceback(self):
        error_output = io.StringIO()

        with (
            patch.object(tg_poller, "_load_offset", return_value=0),
            patch.object(
                tg_poller.urllib.request,
                "urlopen",
                side_effect=RuntimeError("diagnostic boom"),
            ),
            patch.object(tg_poller.time, "sleep", side_effect=StopLoop),
            redirect_stderr(error_output),
            self.assertRaises(StopLoop),
        ):
            tg_poller._loop("test-token", object())

        self.assertIn("RuntimeError: diagnostic boom", error_output.getvalue())


if __name__ == "__main__":
    unittest.main()
