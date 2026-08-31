import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.inventory import ChemicalUsageIn, InsufficientInventory
from app.main import create_app_engine
from app.master_workflow import (
    InvalidCompletion,
    InvalidExecutionDate,
    complete_lead,
    list_due_leads,
    reschedule_lead,
)
from app.models import (
    Base,
    ChemicalUsage,
    Inventory,
    Lead,
    Object,
    Transaction,
    Treatment,
)


class MasterWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_app_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            service_object = Object(
                name="ТЕСТ объект",
                address="Бизнес-адрес",
                type="office",
                area_sqm=Decimal("10.00"),
                risk_points=[],
                status="active",
            )
            inventory = Inventory(
                chemical_name="ТЕСТ препарат",
                quantity=Decimal("10.000"),
                initial_quantity=Decimal("10.000"),
                unit="мл",
                batch_number="TEST-1",
                expiry_date=date(2027, 12, 31),
                supplier="ТЕСТ поставщик",
            )
            session.add_all([service_object, inventory])
            session.commit()
            self.object_id = service_object.id
            self.inventory_id = inventory.id

    def tearDown(self):
        self.engine.dispose()

    def add_lead(
        self,
        session: Session,
        *,
        execution_date: date | None,
        status: str = "new",
        amount: Decimal = Decimal("0.00"),
        object_id: int | None = None,
    ) -> Lead:
        row = Lead(
            source="telegram",
            status=status,
            execution_date=execution_date,
            amount=amount,
            object_id=object_id,
            performed_by="Артём",
        )
        session.add(row)
        session.flush()
        return row

    def test_due_leads_include_only_overdue_and_today_active(self):
        today = date(2026, 8, 31)
        with Session(self.engine) as session:
            overdue = self.add_lead(
                session, execution_date=today - timedelta(days=1), status="in_work"
            )
            current = self.add_lead(session, execution_date=today)
            self.add_lead(session, execution_date=today + timedelta(days=1))
            self.add_lead(session, execution_date=None)
            self.add_lead(session, execution_date=today, status="done")
            self.add_lead(session, execution_date=today, status="cancelled")
            session.commit()

            self.assertEqual(
                [row.id for row in list_due_leads(session, today)],
                [overdue.id, current.id],
            )

    def test_reschedule_accepts_today_and_future_but_rejects_past(self):
        today = date(2026, 8, 31)
        with Session(self.engine) as session:
            lead = self.add_lead(session, execution_date=today)
            session.commit()
            lead_id = lead.id

            for offset in (0, 1, 2, 7):
                updated = reschedule_lead(
                    session, lead_id, today + timedelta(days=offset), today
                )
                self.assertEqual(updated.execution_date, today + timedelta(days=offset))

            with self.assertRaises(InvalidExecutionDate):
                reschedule_lead(session, lead_id, today - timedelta(days=1), today)
            session.refresh(lead)
            self.assertEqual(lead.execution_date, today + timedelta(days=7))

    def test_completion_decrements_inventory_and_creates_one_linked_income(self):
        performed_at = datetime(2026, 8, 31, 9, 30, tzinfo=UTC)
        with Session(self.engine) as session:
            lead = self.add_lead(
                session,
                execution_date=performed_at.date(),
                amount=Decimal("2500.00"),
                object_id=self.object_id,
            )
            session.commit()
            lead_id = lead.id

            result = complete_lead(
                session,
                lead_id=lead_id,
                category="Плесень",
                performed_by="Алексей",
                usages=[
                    ChemicalUsageIn(
                        inventory_id=self.inventory_id,
                        quantity_used=Decimal("1.250"),
                    )
                ],
                without_materials=False,
                completed_at=performed_at,
            )
            self.assertFalse(result.already_done)

            stored_lead = session.get(Lead, lead_id)
            inventory = session.get(Inventory, self.inventory_id)
            treatment = session.scalar(
                select(Treatment).where(Treatment.lead_id == lead_id)
            )
            income = session.scalar(
                select(Transaction).where(Transaction.lead_id == lead_id)
            )
            usage = session.scalar(select(ChemicalUsage))
            assert stored_lead and inventory and treatment and income and usage
            self.assertEqual(inventory.quantity, Decimal("8.750"))
            self.assertEqual(stored_lead.status, "done")
            self.assertEqual(stored_lead.category, "Плесень")
            self.assertEqual(stored_lead.performed_by, "Алексей")
            self.assertIsNotNone(stored_lead.closed_at)
            self.assertEqual(treatment.lead_id, lead_id)
            self.assertEqual(treatment.object_id, self.object_id)
            self.assertEqual(treatment.performed_by, "Алексей")
            self.assertEqual(usage.treatment_id, treatment.id)
            self.assertEqual(usage.quantity, Decimal("1.250"))
            self.assertEqual(income.source, "lead_auto")
            self.assertEqual(income.kind, "income")
            self.assertEqual(income.amount, Decimal("2500.00"))
            self.assertEqual(income.operation_date, performed_at.date())
            self.assertEqual(income.category, "Плесень")
            self.assertEqual(income.object_id, self.object_id)
            self.assertEqual(income.entered_by, "Алексей")
            self.assertFalse(income.review_required)

            repeated = complete_lead(
                session,
                lead_id=lead_id,
                category="Плесень",
                performed_by="Алексей",
                usages=[],
                without_materials=True,
                completed_at=performed_at,
            )
            self.assertTrue(repeated.already_done)
            self.assertEqual(
                session.scalar(
                    select(func.count())
                    .select_from(Transaction)
                    .where(Transaction.lead_id == lead_id)
                ),
                1,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count())
                    .select_from(Treatment)
                    .where(Treatment.lead_id == lead_id)
                ),
                1,
            )

    def test_insufficient_stock_rolls_back_every_side_effect(self):
        performed_at = datetime(2026, 8, 31, 10, 0, tzinfo=UTC)
        with Session(self.engine) as session:
            lead = self.add_lead(
                session,
                execution_date=performed_at.date(),
                amount=Decimal("1000.00"),
                object_id=self.object_id,
            )
            session.commit()
            lead_id = lead.id

            with self.assertRaises(InsufficientInventory):
                complete_lead(
                    session,
                    lead_id=lead_id,
                    category="Дезинсекция",
                    performed_by="Артём",
                    usages=[
                        ChemicalUsageIn(
                            inventory_id=self.inventory_id,
                            quantity_used=Decimal("20.000"),
                        )
                    ],
                    without_materials=False,
                    completed_at=performed_at,
                )

            stored_lead = session.get(Lead, lead_id)
            inventory = session.get(Inventory, self.inventory_id)
            assert stored_lead and inventory
            self.assertEqual(stored_lead.status, "new")
            self.assertEqual(inventory.quantity, Decimal("10.000"))
            self.assertIsNone(session.scalar(select(Treatment)))
            self.assertIsNone(session.scalar(select(ChemicalUsage)))
            self.assertIsNone(session.scalar(select(Transaction)))

    def test_without_materials_records_treatment_and_zero_amount_has_no_income(self):
        performed_at = datetime(2026, 8, 31, 11, 0, tzinfo=UTC)
        with Session(self.engine) as session:
            lead = self.add_lead(
                session,
                execution_date=performed_at.date(),
                object_id=self.object_id,
            )
            session.commit()
            lead_id = lead.id

            result = complete_lead(
                session,
                lead_id=lead_id,
                category="Другие работы",
                performed_by="Артём",
                usages=[],
                without_materials=True,
                completed_at=performed_at,
            )
            self.assertFalse(result.already_done)
            treatment = session.scalar(select(Treatment))
            assert treatment is not None
            self.assertEqual(treatment.lead_id, lead_id)
            self.assertEqual(treatment.chemical_usages, [])
            self.assertIsNone(session.scalar(select(Transaction)))

    def test_completion_validates_object_date_category_and_empty_materials(self):
        performed_at = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
        with Session(self.engine) as session:
            lead = self.add_lead(session, execution_date=None, object_id=None)
            session.commit()

            for category, performer, without_materials in (
                ("Неизвестно", "Артём", True),
                ("Плесень", "Иван", True),
                ("Плесень", "Артём", False),
            ):
                with (
                    self.subTest(category=category, performer=performer),
                    self.assertRaises(InvalidCompletion),
                ):
                    complete_lead(
                        session,
                        lead_id=lead.id,
                        category=category,
                        performed_by=performer,
                        usages=[],
                        without_materials=without_materials,
                        completed_at=performed_at,
                    )


if __name__ == "__main__":
    unittest.main()
