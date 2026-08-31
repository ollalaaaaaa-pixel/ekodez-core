import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app import tg_poller
from app.finance_categories import INCOME_CATEGORIES_V1
from app.models import (
    Base,
    ChemicalUsage,
    Inventory,
    Lead,
    Object,
    TelegramMasterDraft,
    Transaction,
    Treatment,
)
from app.security.pii import protect_lead_pii


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
        self.pii_env = patch.dict(
            os.environ,
            {"PII_FERNET_KEY": Fernet.generate_key().decode("ascii")},
            clear=False,
        )
        self.pii_env.start()

    def tearDown(self):
        self.pii_env.stop()
        self.engine.dispose()

    def test_parses_direction_decimal_amount_and_category(self):
        cases = {
            "купил химию за 3500": (
                "expense",
                Decimal("3500"),
                "Материалы и химия",
            ),
            "потратил 1 250,50 на бензин": (
                "expense",
                Decimal("1250.50"),
                "Топливо и машина",
            ),
            "оплатил аренду 9000": (
                "expense",
                Decimal("9000"),
                "Прочее",
            ),
            "получил 5000 за дезинфекцию": (
                "income",
                Decimal("5000"),
                "Дезинфекция",
            ),
            "перевели нам 7000 за дератизацию": (
                "income",
                Decimal("7000"),
                "Дератизация",
            ),
            "оплатили нам 4200 за насекомых": (
                "income",
                Decimal("4200"),
                "Дезинсекция",
            ),
            "непонятная операция": (
                "unknown",
                Decimal("0.00"),
                "Прочее",
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
            assert row is not None
            self.assertEqual(row.source, "tg_agent")
            self.assertEqual(row.operation_date, date.today())
            self.assertEqual(row.kind, "expense")
            self.assertEqual(row.amount, Decimal("3500.00"))
            self.assertEqual(row.category, "Материалы и химия")
            self.assertTrue(row.review_required)
            tx_id = row.id

        send_message.assert_called_once_with(
            "token",
            101,
            "Черновик: расход 3500 Материалы и химия",
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
                    FakeResponse({"ok": True, "result": {"file_path": "photos/a.jpg"}}),
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
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row.amount, Decimal("0.00"))
            self.assertEqual(row.kind, "unknown")
            self.assertEqual(row.category, "Прочее")
            self.assertTrue(row.review_required)
            self.assertIsNotNone(row.description)
            assert row.description is not None
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
                category="Материалы и химия",
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
            self.assertIsNotNone(row)
            assert row is not None
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

    def _seed_master_lead(self) -> tuple[int, int]:
        source = {
            "client_name": "ТЕСТ Клиент",
            "phone": "89214725000",
            "address": "Архангельск, ТЕСТ улица, 1",
            "comment": "ТЕСТ",
        }
        protected = protect_lead_pii(source, "ТЕСТ")
        with Session(self.engine) as session:
            service_object = Object(
                name="ТЕСТ объект",
                address="Архангельск, объект",
                type="office",
                area_sqm=Decimal("10.00"),
                risk_points=[],
                status="active",
            )
            session.add(service_object)
            session.flush()
            lead = Lead(
                source="telegram",
                client_name=protected["client_name"],
                phone=protected["phone"],
                address=protected["address"],
                comment=protected["comment"],
                raw_text=protected["raw_text"],
                encrypted_pii=protected["encrypted_pii"],
                execution_date=date.today(),
                object_id=service_object.id,
                amount=Decimal("2500.00"),
                status="new",
            )
            inventory = Inventory(
                chemical_name="ТЕСТ препарат",
                quantity=Decimal("10.000"),
                initial_quantity=Decimal("10.000"),
                unit="л",
                batch_number="ТЕСТ-1",
                expiry_date=date(2030, 1, 1),
                supplier="ТЕСТ",
            )
            session.add_all([lead, inventory])
            session.commit()
            return lead.id, inventory.id

    def test_today_reveals_pii_only_to_allowlisted_sender(self):
        lead_id, _ = self._seed_master_lead()
        allowed = {
            "update_id": 700,
            "message": {
                "from": {"id": 101},
                "chat": {"id": 101, "type": "private"},
                "text": "/today",
            },
        }
        unknown = {
            "update_id": 701,
            "message": {
                "from": {"id": 999},
                "chat": {"id": 999, "type": "private"},
                "text": "/today",
            },
        }
        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        with (
            patch.object(tg_poller, "_send_message") as send_message,
            redirect_stdout(captured_stdout),
            redirect_stderr(captured_stderr),
        ):
            tg_poller._process_update(
                "token-marker", self.engine, allowed, {101: "owner"}
            )
            tg_poller._process_update(
                "token-marker", self.engine, unknown, {101: "owner"}
            )

        rendered = "\n".join(str(call) for call in send_message.call_args_list)
        self.assertIn("89214725000", rendered)
        self.assertIn("Архангельск, ТЕСТ улица, 1", rendered)
        self.assertIn(f"mw:done:{lead_id}", rendered)
        self.assertNotIn("999", rendered)
        process_output = captured_stdout.getvalue() + captured_stderr.getvalue()
        for secret_value in (
            "89214725000",
            "Архангельск, ТЕСТ улица, 1",
            "token-marker",
            "101",
            "999",
        ):
            self.assertNotIn(secret_value, process_output)

    def test_material_keyboard_hides_without_materials_after_first_choice(self):
        _, _ = self._seed_master_lead()
        with Session(self.engine) as session:
            initial = tg_poller._inventory_keyboard(
                session, allow_without_materials=True
            )
            subsequent = tg_poller._inventory_keyboard(
                session, allow_without_materials=False
            )

        self.assertIn("mw:none", json.dumps(initial, ensure_ascii=False))
        self.assertNotIn("mw:none", json.dumps(subsequent, ensure_ascii=False))

    def test_master_cancel_clears_draft(self):
        lead_id, _ = self._seed_master_lead()
        with Session(self.engine) as session:
            tg_poller._replace_draft(
                session,
                actor_key="owner",
                lead_id=lead_id,
                action="complete",
                step="confirm",
                payload={"category": "Плесень", "performed_by": "Артём"},
            )

        update = {
            "update_id": 790,
            "callback_query": {
                "id": "mw-cancel",
                "from": {"id": 101},
                "data": "mw:cancel",
                "message": {"message_id": 70, "chat": {"id": 101}},
            },
        }
        with (
            patch.object(tg_poller, "_send_message") as send_message,
            patch.object(tg_poller, "_answer_callback_query"),
        ):
            tg_poller._process_update(
                "token-marker", self.engine, update, {101: "owner"}
            )

        with Session(self.engine) as session:
            self.assertIsNone(session.scalar(select(TelegramMasterDraft).limit(1)))
        self.assertIn("Отменено", str(send_message.call_args_list))

    def test_master_mock_telegram_e2e_is_atomic_and_idempotent(self):
        lead_id, inventory_id = self._seed_master_lead()
        category_index = INCOME_CATEGORIES_V1.index("Плесень")

        def callback(data: str, number: int) -> dict:
            return {
                "update_id": 800 + number,
                "callback_query": {
                    "id": f"mw-{number}",
                    "from": {"id": 101},
                    "data": data,
                    "message": {"message_id": 70 + number, "chat": {"id": 101}},
                },
            }

        sequence = [
            {
                "update_id": 799,
                "message": {
                    "from": {"id": 101},
                    "chat": {"id": 101, "type": "private"},
                    "text": "/today",
                },
            },
            callback(f"mw:done:{lead_id}", 1),
            callback(f"mw:cat:{category_index}", 2),
            callback("mw:who:alexey", 3),
            callback(f"mw:inv:{inventory_id}", 4),
            {
                "update_id": 805,
                "message": {
                    "from": {"id": 101},
                    "chat": {"id": 101, "type": "private"},
                    "text": "1,250",
                },
            },
            callback("mw:finish", 6),
            callback("mw:confirm", 7),
        ]
        with (
            patch.object(tg_poller, "_send_message"),
            patch.object(tg_poller, "_edit_message"),
            patch.object(tg_poller, "_answer_callback_query"),
        ):
            for update in sequence:
                tg_poller._process_update(
                    "token-marker", self.engine, update, {101: "owner"}
                )
            for update in sequence[1:]:
                tg_poller._process_update(
                    "token-marker", self.engine, update, {101: "owner"}
                )

        with Session(self.engine) as session:
            lead = session.get(Lead, lead_id)
            inventory = session.get(Inventory, inventory_id)
            treatments = session.scalars(
                select(Treatment).where(Treatment.lead_id == lead_id)
            ).all()
            transactions = session.scalars(
                select(Transaction).where(Transaction.lead_id == lead_id)
            ).all()
            usages = session.scalars(
                select(ChemicalUsage).where(
                    ChemicalUsage.treatment_id == treatments[0].id
                )
            ).all()
            assert lead is not None and inventory is not None
            self.assertEqual(lead.status, "done")
            self.assertEqual(lead.category, "Плесень")
            self.assertEqual(lead.performed_by, "Алексей")
            self.assertEqual(inventory.quantity, Decimal("8.750"))
            self.assertEqual(len(treatments), 1)
            self.assertEqual(len(usages), 1)
            self.assertEqual(usages[0].quantity, Decimal("1.250"))
            self.assertEqual(len(transactions), 1)
            self.assertEqual(transactions[0].lead_id, lead_id)


if __name__ == "__main__":
    unittest.main()
