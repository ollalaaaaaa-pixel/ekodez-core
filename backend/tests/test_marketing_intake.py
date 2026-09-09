import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import tg_poller
from app.models import Base, Lead, TelegramClientDraft


class MarketingIntakeTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.env = patch.dict(
            os.environ, {"PII_FERNET_KEY": Fernet.generate_key().decode()}
        )
        self.env.start()
        self.now = datetime(2026, 9, 8, 9, 0)

    def tearDown(self):
        self.env.stop()
        self.engine.dispose()

    def send(self, text, update_id, **kwargs):
        from app.marketing_intake import receive_client_message

        return receive_client_message(
            self.engine,
            chat_id=12345,
            sender_id=12345,
            text=text,
            update_id=update_id,
            now=kwargs.pop("now", self.now),
            **kwargs,
        )

    def test_confirmation_creates_one_encrypted_lead_and_replay_repeats_reply(self):
        self.assertIn("СОГЛАСЕН", self.send("/start m_vk", 1))
        self.send("СОГЛАСЕН", 2)
        self.send("Клопы; квартира 45 м²; тестовый адрес", 3)
        self.send("+79210001122", 4)
        with Session(self.engine) as session:
            self.assertEqual(list(session.scalars(select(Lead))), [])
        accepted = self.send("ОТПРАВИТЬ", 5)
        self.assertIn("принята", accepted)
        self.assertEqual(self.send("ОТПРАВИТЬ", 5), accepted)
        with Session(self.engine) as session:
            rows = list(session.scalars(select(Lead)))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].source, "vk")
            self.assertNotIn("+79210001122", rows[0].phone or "")
            self.assertNotIn("тестовый адрес", rows[0].raw_text or "")
            self.assertTrue(rows[0].encrypted_pii)

    def test_expired_encrypted_draft_is_purged_without_new_message(self):
        from app.marketing_intake import purge_expired_client_drafts

        self.send("/start m_avito", 1)
        self.send("СОГЛАСЕН", 2)
        self.send("Описание объекта", 3)
        with Session(self.engine) as session:
            draft = session.scalar(select(TelegramClientDraft))
            self.assertIsNotNone(draft)
            self.assertNotEqual(draft.encrypted_payload, "")
        self.assertEqual(
            purge_expired_client_drafts(self.engine, now=self.now + timedelta(days=2)),
            1,
        )
        with Session(self.engine) as session:
            self.assertEqual(list(session.scalars(select(TelegramClientDraft))), [])

    def test_rate_limit_stops_processing_but_cancel_still_works(self):
        from app.marketing_intake import MAX_MESSAGES_PER_WINDOW

        self.send("/start m_vk", 1)
        for update_id in range(2, MAX_MESSAGES_PER_WINDOW + 1):
            self.send("нет", update_id)
        self.assertIn(
            "слишком много сообщений",
            self.send("СОГЛАСЕН", MAX_MESSAGES_PER_WINDOW + 1).lower(),
        )
        self.assertIn("отменён", self.send("/cancel", MAX_MESSAGES_PER_WINDOW + 2))

    def test_public_private_message_never_falls_through_to_legacy_ingest(self):
        update = {
            "update_id": 100,
            "message": {
                "chat": {"id": 12345, "type": "private"},
                "from": {"id": 12345},
                "text": "id сделки: 800001\nИмя клиента: Тест",
            },
        }
        with (
            patch.object(tg_poller, "_ingest") as ingest,
            patch.object(tg_poller, "_send_message") as send_message,
        ):
            tg_poller._process_update("token", self.engine, update, {})
        ingest.assert_not_called()
        send_message.assert_not_called()

    def test_concurrent_confirmations_create_only_one_lead(self):
        from app.marketing_intake import receive_client_message

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "intake-test.db"
            engine = create_engine(
                f"sqlite:///{path.as_posix()}",
                connect_args={"check_same_thread": False, "timeout": 10},
            )
            Base.metadata.create_all(engine)

            def send(text: str, update_id: int) -> str | None:
                return receive_client_message(
                    engine,
                    chat_id=555,
                    sender_id=555,
                    text=text,
                    update_id=update_id,
                    now=self.now,
                )

            send("/start m_vk", 1)
            send("СОГЛАСЕН", 2)
            send("Описание объекта", 3)
            send("+79210001122", 4)
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda update_id: send("ОТПРАВИТЬ", update_id), [5, 6]))
            with Session(engine) as session:
                self.assertEqual(len(list(session.scalars(select(Lead)))), 1)
            engine.dispose()

    def test_staff_groups_and_nonparticipants_ignored(self):
        self.assertIsNone(self.send("/start m_vk", 1, is_staff=True))
        self.assertIsNone(self.send("/start m_vk", 1, is_private=False))
        self.assertIsNone(self.send("ОТПРАВИТЬ", 2))

    def test_no_key_no_data_and_unknown_source_not_accepted(self):
        self.assertIsNone(self.send("/start m_secret", 1))
        with patch.dict(os.environ, {"PII_FERNET_KEY": ""}):
            self.assertIn("недоступен", self.send("/start m_vk", 2))
        with Session(self.engine) as session:
            self.assertEqual(list(session.scalars(select(Lead))), [])

    def test_expiry_cancel_and_invalid_contact_do_not_create_lead(self):
        self.send("/start m_avito", 1)
        self.send("СОГЛАСЕН", 2)
        self.send("Описание объекта", 3)
        self.assertIn("телефон", self.send("не телефон", 4))
        self.assertIn(
            "истёк", self.send("ОТПРАВИТЬ", 5, now=self.now + timedelta(days=2))
        )
        self.send("/start m_vk", 6, now=self.now + timedelta(days=2))
        self.assertIn(
            "отменён", self.send("/cancel", 7, now=self.now + timedelta(days=2))
        )
        with Session(self.engine) as session:
            self.assertEqual(list(session.scalars(select(Lead))), [])
