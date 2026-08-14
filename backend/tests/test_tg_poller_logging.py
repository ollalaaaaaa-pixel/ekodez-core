import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app import tg_poller
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
    def test_ingest_logs_external_id_after_successful_commit(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        output = io.StringIO()

        with redirect_stdout(output):
            tg_poller._ingest(engine, "id сделки: 999100")

        with Session(engine) as session:
            count = session.scalar(select(func.count()).select_from(Lead))
        self.assertEqual(count, 1)
        self.assertIn("lead ingested: 999100", output.getvalue())

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
