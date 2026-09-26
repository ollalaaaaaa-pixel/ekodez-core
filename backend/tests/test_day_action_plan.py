import os
import time
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import main
from app.master_workflow import moscow_today
from app.models import (
    Base,
    Contract,
    ContractPeriod,
    Inventory,
    Lead,
    Object,
    Transaction,
)
from app.security import tg_auth
from tests.auth_helpers import login_telegram


class DayActionPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "TELEGRAM_BOT_TOKEN": "synthetic-plan-token",
                "OWNER_TG_ID": "101",
                "ALEXEY_TG_ID": "202",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.engine = main.create_app_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        original_engine = main.engine
        main.engine = self.engine
        self.addCleanup(setattr, main, "engine", original_engine)
        self.client = TestClient(main.app, client=("127.0.0.1", 51000))
        self.addCleanup(self.client.close)

    def test_moscow_boundary_and_due_lead_selection(self) -> None:
        self.assertEqual(
            moscow_today(datetime(2026, 9, 24, 21, 30, tzinfo=UTC)),
            date(2026, 9, 25),
        )
        with Session(self.engine) as session:
            rows = [
                Lead(
                    status="new",
                    execution_date=date(2026, 9, 24),
                    performed_by="Алексей",
                ),
                Lead(
                    status="in_work",
                    execution_date=date(2026, 9, 25),
                    performed_by="Артём",
                ),
                Lead(
                    status="new",
                    execution_date=date(2026, 9, 26),
                    performed_by="Алексей",
                ),
                Lead(status="new", execution_date=None, performed_by="Алексей"),
                Lead(
                    status="done",
                    execution_date=date(2026, 9, 24),
                    performed_by="Алексей",
                ),
                Lead(
                    status="cancelled",
                    execution_date=date(2026, 9, 24),
                    performed_by="Алексей",
                ),
            ]
            session.add_all(rows)
            session.commit()
            expected = [rows[0].id, rows[1].id]
        with patch(
            "app.main.moscow_today", return_value=date(2026, 9, 25), create=True
        ):
            self.assertEqual(
                login_telegram(self.client, 101, "synthetic-plan-token").status_code,
                200,
            )
            response = self.client.get("/api/day/action-plan")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["items"] if item["kind"] == "lead"],
            expected,
        )

    def test_master_sees_only_alexey_and_linked_objects_without_pii(self) -> None:
        with Session(self.engine) as session:
            own_object = Object(
                name="Разрешённый",
                address="Секретная улица",
                type="office",
                area_sqm=Decimal("10.00"),
                status="active",
                next_treatment_date=date(2026, 9, 25),
            )
            other_object = Object(
                name="Чужой клиент",
                address="Чужой адрес",
                type="office",
                area_sqm=Decimal("10.00"),
                status="active",
                next_treatment_date=date(2026, 9, 25),
            )
            session.add_all([own_object, other_object])
            session.flush()
            own_lead = Lead(
                status="new",
                execution_date=date(2026, 9, 25),
                performed_by="Алексей",
                object_id=own_object.id,
                client_name="Секретное имя",
            )
            other_lead = Lead(
                status="new",
                execution_date=date(2026, 9, 25),
                performed_by="Артём",
                object_id=other_object.id,
                client_name="Чужой клиент",
            )
            session.add_all([own_lead, other_lead])
            session.commit()
            own_id = own_lead.id
        self.assertEqual(
            login_telegram(self.client, 202, "synthetic-plan-token").status_code, 200
        )
        with patch(
            "app.main.moscow_today", return_value=date(2026, 9, 25), create=True
        ):
            response = self.client.get("/api/day/action-plan")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(
            [item["id"] for item in body["items"] if item["kind"] == "lead"], [own_id]
        )
        self.assertEqual(body["counts"]["object_due"], 1)
        self.assertEqual(
            [item for item in body["items"] if item["kind"] == "object"], []
        )
        self.assertTrue(
            next(
                item
                for item in body["items"]
                if item["id"] == own_id and item["kind"] == "lead"
            )["linked_object_due"]
        )
        self.assertNotIn("Секретное имя", response.text)
        self.assertNotIn("Секретная улица", response.text)
        self.assertNotIn("Чужой клиент", response.text)

    def test_counts_cover_all_rows_but_cards_stop_at_five(self) -> None:
        with Session(self.engine) as session:
            session.add_all(
                Lead(
                    status="new", execution_date=date(2026, 9, 24), performed_by="Артём"
                )
                for _ in range(6)
            )
            session.add(
                Inventory(
                    chemical_name="Тест",
                    quantity=Decimal("0.5"),
                    initial_quantity=Decimal("10"),
                    unit="л",
                    batch_number="B1",
                    expiry_date=date(2027, 1, 1),
                    supplier="Тест",
                )
            )
            session.commit()
        self.assertEqual(
            login_telegram(self.client, 101, "synthetic-plan-token").status_code, 200
        )
        with patch(
            "app.main.moscow_today", return_value=date(2026, 9, 25), create=True
        ):
            response = self.client.get("/api/day/action-plan")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["counts"]["lead_overdue"], 6)
        self.assertEqual(
            len([item for item in body["items"] if item["kind"] == "lead"]), 5
        )
        self.assertEqual(body["counts"]["inventory_low"], 1)
        with patch("app.main.moscow_today", return_value=date(2026, 9, 25)):
            full_body = self.client.get("/api/day/action-plan?all=true").json()
        self.assertEqual(
            len([item for item in full_body["items"] if item["kind"] == "lead"]), 6
        )
        self.assertEqual(len(full_body["group_ids"]["lead"]), 6)

    def test_overdue_object_precedes_today_leads_in_global_priority(self) -> None:
        with Session(self.engine) as session:
            session.add_all(
                Lead(status="new", execution_date=date(2026, 9, 25)) for _ in range(3)
            )
            session.add(
                Object(
                    name="Объект",
                    address="Тестовая 1",
                    type="office",
                    area_sqm=Decimal("10"),
                    status="active",
                    next_treatment_date=date(2026, 9, 23),
                )
            )
            session.commit()
        login_telegram(self.client, 101, "synthetic-plan-token")
        with patch("app.main.moscow_today", return_value=date(2026, 9, 25)):
            body = self.client.get("/api/day/action-plan").json()
        self.assertEqual(body["items"][0]["kind"], "object")
        self.assertEqual(body["counts"]["object_overdue"], 1)
        self.assertEqual(body["counts"]["object_today"], 0)

    def test_master_sees_due_object_linked_to_future_active_lead(self) -> None:
        with Session(self.engine) as session:
            obj = Object(
                name="Объект",
                address="Тестовая 1",
                type="office",
                area_sqm=Decimal("10"),
                status="active",
                next_treatment_date=date(2026, 9, 25),
            )
            session.add(obj)
            session.flush()
            session.add(
                Lead(
                    status="in_work",
                    execution_date=date(2026, 9, 26),
                    performed_by="Алексей",
                    object_id=obj.id,
                )
            )
            session.commit()
            object_id = obj.id
        login_telegram(self.client, 202, "synthetic-plan-token")
        with patch("app.main.moscow_today", return_value=date(2026, 9, 25)):
            body = self.client.get("/api/day/action-plan").json()
        self.assertIn(
            object_id,
            [item["id"] for item in body["items"] if item["kind"] == "object"],
        )

    def test_object_is_not_hidden_when_linked_lead_exceeds_card_limit(self) -> None:
        with Session(self.engine) as session:
            obj = Object(
                name="Объект",
                address="Тестовая 1",
                type="office",
                area_sqm=Decimal("10"),
                status="active",
                next_treatment_date=date(2026, 9, 25),
            )
            session.add(obj)
            session.flush()
            session.add_all(
                Lead(status="new", execution_date=date(2026, 9, 24)) for _ in range(5)
            )
            session.add(
                Lead(
                    status="new",
                    execution_date=date(2026, 9, 25),
                    object_id=obj.id,
                )
            )
            session.commit()
            object_id = obj.id
        login_telegram(self.client, 101, "synthetic-plan-token")
        with patch("app.main.moscow_today", return_value=date(2026, 9, 25)):
            body = self.client.get("/api/day/action-plan").json()
        self.assertIn(
            object_id,
            [item["id"] for item in body["items"] if item["kind"] == "object"],
        )

    def test_25th_day_document_cue_targets_current_month_package(self) -> None:
        with Session(self.engine) as session:
            contract = Contract(number="T-2", price=Decimal("3000.00"))
            session.add(contract)
            session.flush()
            obj = Object(
                name="Объект",
                address="Тестовая 1",
                type="office",
                area_sqm=Decimal("10"),
                status="active",
                contract_id=contract.id,
            )
            session.add(obj)
            session.commit()
            object_id = obj.id
        login_telegram(self.client, 101, "synthetic-plan-token")
        with patch("app.main.moscow_today", return_value=date(2026, 9, 25)):
            body = self.client.get("/api/day/action-plan").json()
        cue = next(item for item in body["items"] if item["status"] == "акт к выпуску")
        self.assertEqual(cue["target"]["id"], object_id)
        self.assertEqual(cue["target"]["periodMonth"], "2026-09")

    def test_anonymous_is_rejected(self) -> None:
        self.assertEqual(self.client.get("/api/day/action-plan").status_code, 401)

    def test_signed_session_with_other_role_is_forbidden(self) -> None:
        token = tg_auth._signed_value(
            {"role": "auditor", "exp": int(time.time()) + 3600}, "session"
        )
        self.client.cookies.set(tg_auth.SESSION_COOKIE, token)
        self.assertEqual(self.client.get("/api/day/action-plan").status_code, 403)

    def test_different_due_dates_keep_both_lead_and_object(self) -> None:
        with Session(self.engine) as session:
            obj = Object(
                name="Объект",
                address="Тестовая",
                type="office",
                area_sqm=Decimal("10"),
                status="active",
                next_treatment_date=date(2026, 9, 24),
            )
            session.add(obj)
            session.flush()
            session.add(
                Lead(status="new", execution_date=date(2026, 9, 25), object_id=obj.id)
            )
            session.commit()
        login_telegram(self.client, 101, "synthetic-plan-token")
        with patch("app.main.moscow_today", return_value=date(2026, 9, 25)):
            items = self.client.get("/api/day/action-plan").json()["items"]
        self.assertEqual([item["kind"] for item in items[:2]], ["object", "lead"])

    def test_review_transactions_are_capped_after_date_sort(self) -> None:
        with Session(self.engine) as session:
            for day in (20, 21, 22, 23, 24, 19):
                session.add(
                    Transaction(
                        source="manual",
                        operation_date=date(2026, 9, day),
                        amount=Decimal("1"),
                        kind="expense",
                        review_required=True,
                    )
                )
            session.commit()
        login_telegram(self.client, 101, "synthetic-plan-token")
        with patch("app.main.moscow_today", return_value=date(2026, 9, 25)):
            items = self.client.get("/api/day/action-plan").json()["items"]
        dates = [item["due_date"] for item in items if item["kind"] == "transaction"]
        self.assertEqual(dates, [f"2026-09-{day:02d}" for day in (19, 20, 21, 22, 23)])

    def test_owner_decisions_precede_low_stock_regardless_of_date(self) -> None:
        with Session(self.engine) as session:
            session.add(
                Transaction(
                    source="manual",
                    operation_date=date(2026, 10, 1),
                    amount=Decimal("1"),
                    kind="expense",
                    review_required=True,
                )
            )
            session.add(
                Inventory(
                    chemical_name="Средство",
                    quantity=Decimal("0"),
                    initial_quantity=Decimal("10"),
                    unit="л",
                    batch_number="test",
                    expiry_date=date(2027, 1, 1),
                    supplier="Тест",
                )
            )
            session.commit()
        login_telegram(self.client, 101, "synthetic-plan-token")
        with patch("app.main.moscow_today", return_value=date(2026, 9, 25)):
            items = self.client.get("/api/day/action-plan").json()["items"]
        self.assertEqual([item["kind"] for item in items], ["transaction", "inventory"])

    def test_action_plan_cache_expires_after_five_minutes(self) -> None:
        login_telegram(self.client, 101, "synthetic-plan-token")
        with (
            patch("app.main.moscow_today", return_value=date(2026, 9, 25)),
            patch("app.main.monotonic", side_effect=(100.0, 200.0, 401.0)),
            patch("app.main.build_action_plan", return_value={"items": []}) as build,
        ):
            for _ in range(3):
                self.assertEqual(
                    self.client.get("/api/day/action-plan").status_code, 200
                )
        self.assertEqual(build.call_count, 2)

    def test_owner_sees_document_cues_and_review_transactions(self) -> None:
        with Session(self.engine) as session:
            contract = Contract(number="T-1", price=Decimal("3000.00"))
            session.add(contract)
            session.flush()
            session.add(
                Object(
                    name="Секретный объект",
                    address="Секретный адрес",
                    type="office",
                    area_sqm=Decimal("20"),
                    status="active",
                    contract_id=contract.id,
                )
            )
            session.add_all(
                [
                    ContractPeriod(
                        contract_id=contract.id,
                        period_month=date(2026, 9, 1),
                        paid_service_due=True,
                        work_act_status="draft",
                        generated_at=datetime(2026, 9, 2),
                        invoice_number=None,
                    ),
                    Transaction(
                        source="manual",
                        operation_date=date(2026, 9, 24),
                        amount=Decimal("100"),
                        kind="expense",
                        review_required=True,
                        counterparty="Секретное имя",
                        counterparty_inn="2901000000",
                    ),
                ]
            )
            session.commit()
        self.assertEqual(
            login_telegram(self.client, 101, "synthetic-plan-token").status_code, 200
        )
        with patch(
            "app.main.moscow_today", return_value=date(2026, 9, 25), create=True
        ):
            response = self.client.get("/api/day/action-plan")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        statuses = {
            item["status"] for item in body["items"] if item["kind"] == "document"
        }
        self.assertIn("черновик акта", statuses)
        self.assertIn("проверить счёт", statuses)
        self.assertEqual(body["counts"]["transaction_review"], 1)
        self.assertNotIn("Секретн", response.text)
        self.assertNotIn("2901000000", response.text)

    def test_master_gets_no_document_or_finance_cues(self) -> None:
        with Session(self.engine) as session:
            session.add(
                Transaction(
                    source="manual",
                    operation_date=date(2026, 9, 24),
                    amount=Decimal("100"),
                    kind="expense",
                    review_required=True,
                )
            )
            session.commit()
        self.assertEqual(
            login_telegram(self.client, 202, "synthetic-plan-token").status_code, 200
        )
        with patch(
            "app.main.moscow_today", return_value=date(2026, 9, 25), create=True
        ):
            response = self.client.get("/api/day/action-plan")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            any(
                item["kind"] in ("document", "transaction")
                for item in response.json()["items"]
            )
        )
        self.assertNotIn("transaction_review", response.json()["counts"])
