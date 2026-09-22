import csv
import io
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from html import escape
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import main
from app.gnom_parser import (
    HEADERS,
    GnomError,
    extract,
    normalized_address,
    parse_gnom,
    phones,
)
from app.gnom_scheduler import run_gnom_weekly
from app.gnom_service import import_file
from app.marketing_metrics import marketing_metrics
from app.models import (
    Base,
    Client,
    GnomCandidate,
    GnomRecord,
    GnomSettings,
    GnomWeeklyRun,
    Lead,
    Object,
    Transaction,
    TransactionCategory,
    Treatment,
)
from tests.auth_helpers import login_telegram

TEST_PHONE = "+7" + "900" + "123" + "45" + "67"
TEST_NAME = "Тестовый Клиентсинтетика"


def fixture(**changes):
    row = dict.fromkeys(HEADERS, "")
    row.update(
        Start="2026-08-20 12:00",
        End="2026-08-20 13:00",
        Created="2026-08-19 12:00",
        Address="Архангельск, ул. Тестовая, д. 1, кв. 2",
        Income="2500",
        Outcome="500",
        Finished="true",
        Comments=(
            f"Имя клиента: {TEST_NAME}\nТелефон: {TEST_PHONE}\nid сделки: 123\n"
            "клопы база 2 500 усил +500 гсм 2кк договор Повторка ПЕРЕНОС "
            "холодный туман дети собака\nПрепарат: ТЕСТ средство\n"
            "Вы напарник: Тестнапарник +7(900)765-43-21"
        ),
    )
    row.update(changes)
    return row


def csv_bytes(rows):
    output = io.StringIO()
    writer = csv.DictWriter(output, HEADERS)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


class GnomParserTest(unittest.TestCase):
    def test_formats_csv_xlsx_html_xls_and_signals(self):
        row = fixture()
        book = Workbook()
        assert book.active is not None
        book.active.append(list(HEADERS))
        book.active.append([row[key] for key in HEADERS])
        output = io.BytesIO()
        book.save(output)
        book.close()
        html = (
            "<table>"
            + "".join(
                "<tr>"
                + "".join(
                    "<td>" + escape(cell).replace("\n", "<br>") + "</td>"
                    for cell in cells
                )
                + "</tr>"
                for cells in (list(HEADERS), [row[key] for key in HEADERS])
            )
            + "</table>"
        )
        for content in (csv_bytes([row]), output.getvalue(), html.encode()):
            parsed = parse_gnom(content)[0]
            self.assertEqual(parsed.phone_values, [TEST_PHONE])
            self.assertEqual(parsed.name, TEST_NAME)
            self.assertEqual(parsed.signals["source"], "aggregator")
            self.assertEqual(parsed.signals["base_price"], "2500.00")
            self.assertEqual(parsed.signals["fuel_price"], "500.00")
            self.assertEqual(parsed.signals["area_unit"], "rooms")
            self.assertTrue(parsed.signals["repeat"])
            self.assertTrue(parsed.signals["rescheduled"])
            self.assertIn("холодный туман", parsed.signals["methods"])
            self.assertNotIn(
                "Тестнапарник", json.dumps(parsed.signals, ensure_ascii=False)
            )

    def test_attribution_typo_taken_order_and_labels(self):
        cases = [
            ("d сделки: 456", "aggregator", "456"),
            ("Вы взяли заказ №789 в работу", "aggregator", "789"),
            ("Агрегаторы", "aggregator", None),
            ("Заявка с авито", "avito", None),
            ("Заявка с Яндекса", "yandex", None),
            ("Звонок", "phone", None),
            ("Вы напарник: id сделки: 77", "other", None),
        ]
        for comment, source, deal in cases:
            row = extract(fixture(Comments=comment))
            self.assertEqual(
                (row.signals["source"], row.signals["deal_id"]), (source, deal)
            )
        for area, unit in [
            ("1шка", "rooms"),
            ("3ка", "rooms"),
            ("50м2", "m2"),
            ("6 сотки", "sotki"),
        ]:
            self.assertEqual(extract(fixture(Comments=area)).signals["area_unit"], unit)

    def test_phone_and_address_normalization(self):
        self.assertEqual(
            phones("8 (900) 123-45-67; 9001234567; +7.900.123.45.67"), [TEST_PHONE]
        )
        self.assertEqual(
            normalized_address("г. Архангельск, ул. Тестовая, д.1, кв.2"),
            normalized_address("Архангельск улица Тестовая дом 1 квартира 2"),
        )
        with self.assertRaises(GnomError):
            parse_gnom(b"bad file")


class GnomIntegrationTest(unittest.TestCase):
    def setUp(self):
        env = patch.dict(
            os.environ,
            {
                "PII_FERNET_KEY": Fernet.generate_key().decode(),
                "TELEGRAM_BOT_TOKEN": "synthetic-gnom-token",
                "OWNER_TG_ID": "101",
                "ALEXEY_TG_ID": "202",
                "HTTPS_ENABLED": "0",
            },
        )
        env.start()
        self.addCleanup(env.stop)
        self.engine = main.create_app_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        original = main.engine
        main.engine = self.engine
        self.addCleanup(setattr, main, "engine", original)
        poller = patch.object(main, "start_poller")
        scheduler = patch.object(main, "start_report_scheduler")
        poller.start()
        scheduler.start()
        self.addCleanup(poller.stop)
        self.addCleanup(scheduler.stop)
        self.addCleanup(self.engine.dispose)
        self.client = TestClient(main.app, client=("127.0.0.1", 51000))
        self.addCleanup(self.client.close)
        self.assertEqual(
            login_telegram(self.client, 101, "synthetic-gnom-token").status_code, 200
        )

    def test_cancelled_correction_removes_treatment_and_last_date(self):
        import_file(self.engine, csv_bytes([fixture()]), "test.csv", authorized=True)
        import_file(
            self.engine,
            csv_bytes([fixture(Cancelled="true")]),
            "test.csv",
            authorized=True,
        )
        with Session(self.engine) as session:
            self.assertEqual(list(session.scalars(select(Treatment))), [])
            obj = session.scalar(select(Object))
            assert obj is not None
            self.assertIsNone(obj.last_treatment_date)

    def test_import_upsert_expense_confirmation_pii_and_repeat(self):
        content = csv_bytes([fixture()])
        with self.assertRaises(GnomError):
            import_file(self.engine, content, "history.csv")
        result = import_file(self.engine, content, "history.csv", authorized=True)
        self.assertEqual(result["created"], 1)
        self.assertEqual(
            import_file(self.engine, content, "history.csv", authorized=True)[
                "unchanged"
            ],
            1,
        )
        with Session(self.engine) as session:
            self.assertEqual(len(list(session.scalars(select(Transaction)))), 1)
            session.add(
                TransactionCategory(
                    title="ГСМ", kind="expense", sort_order=0, is_active=True
                )
            )
            session.commit()
            record = session.scalar(select(GnomRecord))
            assert record is not None
            record_id = record.id
            lead = session.get(Lead, record.lead_id)
            assert lead is not None
            self.assertIsNone(lead.partner)
            self.assertEqual(len(list(session.scalars(select(Treatment)))), 1)
            self.assertTrue(lead.encrypted_pii)
            for table in Base.metadata.sorted_tables:
                if table.name == "consumed_challenges":
                    continue
                values = str(
                    session.execute(text(f'SELECT * FROM "{table.name}"')).all()
                )
                for secret in (TEST_PHONE, TEST_NAME, "Тестнапарник", "Тестовая"):
                    self.assertNotIn(secret, values, table.name)
        response = self.client.post(
            f"/api/gnom/records/{record_id}/expense", json={"category_id": 1}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            self.client.post(
                f"/api/gnom/records/{record_id}/expense", json={"category_id": 1}
            ).json(),
            response.json(),
        )
        self.assertEqual(
            import_file(
                self.engine,
                csv_bytes([fixture(Income="3000")]),
                "history.csv",
                authorized=True,
            )["updated"],
            1,
        )
        with Session(self.engine) as session:
            self.assertEqual(len(list(session.scalars(select(Client)))), 1)
            self.assertEqual(len(list(session.scalars(select(Object)))), 1)
            self.assertEqual(len(list(session.scalars(select(Transaction)))), 2)
            metrics = marketing_metrics(
                session, datetime(2026, 8, 1).date(), datetime(2026, 8, 31).date()
            )
            self.assertEqual(
                next(
                    row for row in metrics["channels"] if row["source"] == "aggregators"
                )["paid_revenue"],
                "3000.00",
            )
        repeat = self.client.post("/api/gnom/repeat", json={"phone": TEST_PHONE})
        self.assertEqual(repeat.status_code, 200)
        self.assertEqual(repeat.json()["price"], "3000.00")
        created = self.client.post(
            "/api/leads/ingest",
            json={
                "source": "phone",
                "text": (
                    f"Телефон: {TEST_PHONE}\n"
                    "Адрес: Архангельск, ул. Тестовая, д. 1, кв. 2"
                ),
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertTrue(created.json()["is_repeat"])
        hint = self.client.get(
            "/api/gnom/price-hint",
            params={"pest": "клопы", "city": "Архангельск", "area_unit": "rooms"},
        )
        self.assertEqual(hint.json()["median_price"], "3000.00")
        self.assertEqual(created.json()["amount"], "0.00")

    def test_repeat_price_hint_and_lead_history_are_owner_only(self):
        cases = [
            ("POST", "/api/gnom/repeat", {"json": {"phone": TEST_PHONE}}),
            ("GET", "/api/gnom/leads/1/history", {}),
            (
                "GET",
                "/api/gnom/price-hint",
                {
                    "params": {
                        "pest": "клопы",
                        "city": "Архангельск",
                        "area_unit": "rooms",
                    }
                },
            ),
        ]
        with TestClient(main.app, client=("127.0.0.1", 51001)) as anonymous:
            for method, url, kwargs in cases:
                self.assertEqual(
                    anonymous.request(method, url, **kwargs).status_code, 401
                )
        with TestClient(main.app, client=("127.0.0.1", 51002)) as master:
            self.assertEqual(
                login_telegram(master, 202, "synthetic-gnom-token").status_code,
                200,
            )
            for method, url, kwargs in cases:
                self.assertEqual(master.request(method, url, **kwargs).status_code, 403)

    def test_conflicting_duplicate_rolls_back_entire_file_and_no_seed(self):
        with self.assertRaises(GnomError):
            import_file(
                self.engine,
                csv_bytes([fixture(), fixture(Income="9000")]),
                "history.csv",
                authorized=True,
            )
        with Session(self.engine) as session:
            for model in (Lead, Client, Object, Transaction, GnomRecord, GnomCandidate):
                self.assertEqual(list(session.scalars(select(model))), [])

    def test_owner_gate_candidates_and_platform_memory(self):
        import_file(self.engine, csv_bytes([fixture()]), "history.csv", authorized=True)
        overview = self.client.get("/api/gnom/overview").json()
        candidate = overview["candidates"][0]
        self.assertEqual(candidate["status"], "pending")
        self.assertNotIn("ТЕСТ средство", json.dumps(overview, ensure_ascii=False))
        self.assertEqual(
            self.client.patch(
                "/api/gnom/records/1/platform",
                json={"platform": "Тестплатформа", "deal_prefix": "12"},
            ).status_code,
            200,
        )
        import_file(
            self.engine,
            csv_bytes(
                [
                    fixture(
                        Start="2026-08-21 12:00",
                        Comments="id сделки: 124\nТелефон: " + TEST_PHONE,
                    )
                ]
            ),
            "second.csv",
            authorized=True,
        )
        with Session(self.engine) as session:
            remembered = session.scalar(
                select(GnomRecord).where(GnomRecord.deal_id == "124")
            )
            assert remembered is not None
            self.assertEqual(
                remembered.platform,
                "Тестплатформа",
            )
        self.assertEqual(
            login_telegram(self.client, 202, "synthetic-gnom-token").status_code, 200
        )
        self.assertEqual(self.client.get("/api/gnom/overview").status_code, 403)
        self.assertEqual(
            self.client.post(
                "/api/gnom/import?confirmed=true",
                files={"file": ("a.csv", csv_bytes([fixture()]))},
            ).status_code,
            403,
        )

    def test_weekly_requires_owner_enable_and_is_idempotent(self):
        monday = datetime(2026, 9, 21, 9, 10, tzinfo=ZoneInfo("Europe/Moscow"))
        messages = []

        def sender(message):
            messages.append(message)
            return True

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "synthetic.csv").write_bytes(csv_bytes([fixture()]))
            self.assertFalse(run_gnom_weekly(self.engine, monday, sender, root))
            self.client.patch(
                "/api/gnom/settings", json={"weekly_enabled": True, "warranty_days": 30}
            )
            with patch("app.gnom_scheduler.IMPORT_ROOT", root):
                self.assertTrue(run_gnom_weekly(self.engine, monday, sender, root))
                self.assertFalse(run_gnom_weekly(self.engine, monday, sender, root))
            with Session(self.engine) as session:
                self.assertEqual(len(list(session.scalars(select(GnomRecord)))), 1)
        self.assertEqual(len(messages), 1)
        self.assertNotIn(TEST_PHONE, messages[0])
        self.assertNotIn(TEST_NAME, messages[0])

    def test_weekly_recovers_stale_running_lease(self):
        monday = datetime(2026, 9, 14, 11, 10, tzinfo=UTC)
        sent: list[str] = []

        def sender(message: str) -> bool:
            sent.append(message)
            return True

        with Session(self.engine) as session, session.begin():
            session.add(GnomSettings(id=1, weekly_enabled=True))
            session.add(
                GnomWeeklyRun(
                    week=monday.astimezone(ZoneInfo("Europe/Moscow")).date(),
                    status="running",
                    started_at=monday - timedelta(hours=2),
                )
            )
        with tempfile.TemporaryDirectory() as temporary:
            self.assertTrue(
                run_gnom_weekly(
                    self.engine,
                    monday,
                    sender,
                    Path(temporary),
                )
            )
        self.assertEqual(len(sent), 1)
