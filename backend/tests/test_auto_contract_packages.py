import os
import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.auto_contract_packages import (
    AutoPackageDraft,
    format_auto_package_summary,
    run_auto_contract_packages,
    run_scheduled_auto_contract_packages,
)
from app.models import (
    Base,
    Client,
    Contract,
    ContractPeriod,
    InspectionReport,
    Object,
    Treatment,
)
from app.reports.daily import send_daily_report


class AutoContractPackagesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def _contract(
        self,
        session: Session,
        *,
        number: str = "ТЕСТ-01",
        periodicity: str | None = "monthly",
        inspection_price: Decimal | None = Decimal("3000.00"),
        status: str = "active",
        start_date: date | None = None,
        end_date: date | None = None,
        with_object: bool = True,
        client_type: str = "legal_entity",
    ) -> Contract:
        contract = Contract(
            number=number,
            price=Decimal("5000.00"),
            inspection_price=inspection_price,
            periodicity=periodicity,
            service_months=[],
            start_date=start_date,
            end_date=end_date,
        )
        session.add(contract)
        if with_object:
            service_object = Object(
                name=f"Объект {number}",
                address="ТЕСТ адрес",
                type="other",
                area_sqm=Decimal("100.00"),
                risk_points=[],
                status=status,
                contract=contract,
            )
            session.add(service_object)
            session.flush()
            session.add(
                Client(
                    name="ТЕСТ клиент",
                    client_type=client_type,
                    object_id=service_object.id,
                )
            )
        session.flush()
        return contract

    @staticmethod
    def _generator(draft: AutoPackageDraft) -> list[dict[str, object]]:
        count = 4 if draft.treatment is not None else 2
        return [
            {
                "version": 1,
                "kind": f"doc-{index}",
                "name": f"doc-{index}.docx",
                "size": 1,
                "sha256": "0" * 64,
            }
            for index in range(count)
        ]

    def test_scheduler_runs_only_on_first_for_previous_month(self):
        with Session(self.engine) as session:
            self._contract(session)
            session.commit()
            skipped = run_scheduled_auto_contract_packages(
                session, date(2026, 10, 2), self._generator
            )
            self.assertIsNone(skipped)
            self.assertEqual(session.scalar(select(ContractPeriod.id)), None)

            result = run_scheduled_auto_contract_packages(
                session, date(2026, 10, 1), self._generator
            )
            assert result is not None
            self.assertEqual(result.period_month, date(2026, 9, 1))
            self.assertEqual(result.ready, ("Объект ТЕСТ-01",))

    def test_active_boundaries_null_bounds_and_stored_status(self):
        with Session(self.engine) as session:
            self._contract(
                session,
                number="начало-на-границе",
                start_date=date(2026, 9, 30),
            )
            self._contract(
                session,
                number="конец-на-границе",
                end_date=date(2026, 9, 1),
            )
            self._contract(
                session,
                number="ещё-не-начался",
                start_date=date(2026, 10, 1),
            )
            self._contract(
                session,
                number="уже-закончился",
                end_date=date(2026, 8, 31),
            )
            overdue = self._contract(session, number="overdue-хранимый-active")
            assert overdue.object is not None
            overdue.object.next_treatment_date = date(2026, 8, 1)
            self._contract(session, number="inactive", status="inactive")
            self._contract(
                session,
                number="inactive-без-цены",
                status="inactive",
                inspection_price=None,
            )
            self._contract(
                session,
                number="физлицо-без-цены",
                client_type="individual",
                inspection_price=None,
            )
            session.commit()

            result = run_auto_contract_packages(
                session, date(2026, 9, 1), self._generator
            )
            self.assertEqual(
                set(result.ready),
                {
                    "Объект начало-на-границе",
                    "Объект конец-на-границе",
                    "Объект overdue-хранимый-active",
                },
            )
            labels = {row.label for row in result.skipped}
            self.assertNotIn("Объект inactive-без-цены", labels)
            reasons = {row.label: row.reasons for row in result.skipped}
            self.assertEqual(
                reasons["Объект физлицо-без-цены"],
                (
                    "тип плательщика не поддерживается",
                    "не задана цена обследования",
                ),
            )

    def test_reasons_are_aggregated_and_existing_rows_are_silent(self):
        with Session(self.engine) as session:
            not_configured = self._contract(
                session,
                number="не-настроен",
                periodicity=None,
                inspection_price=None,
            )
            self._contract(session, number="без-цены", inspection_price=None)
            no_object = self._contract(session, number="без-объекта", with_object=False)
            existing_report = self._contract(session, number="есть-осмотр")
            existing_period = self._contract(session, number="есть-период")
            session.add_all(
                [
                    InspectionReport(
                        contract=existing_report,
                        report_month=date(2026, 9, 1),
                    ),
                    ContractPeriod(
                        contract=existing_period,
                        period_month=date(2026, 9, 1),
                        paid_service_due=True,
                    ),
                ]
            )
            session.commit()

            result = run_auto_contract_packages(
                session, date(2026, 9, 1), self._generator
            )
            reasons = {row.label: row.reasons for row in result.skipped}
            self.assertEqual(
                reasons["Объект не-настроен"],
                ("договор не настроен", "не задана цена обследования"),
            )
            self.assertEqual(
                reasons["Объект без-цены"], ("не задана цена обследования",)
            )
            self.assertEqual(reasons[f"Договор {no_object.number}"], ("нет объекта",))
            self.assertNotIn("Объект есть-осмотр", reasons)
            self.assertNotIn("Объект есть-период", reasons)
            self.assertEqual(not_configured.inspection_reports, [])

    def test_monthly_and_service_months_schedule(self):
        with Session(self.engine) as session:
            self._contract(session, number="ежемесячный")
            march = self._contract(
                session, number="март-сентябрь", periodicity="semiannual"
            )
            march.service_months = [3, 9]
            april = self._contract(
                session,
                number="апрель-октябрь",
                periodicity="custom",
                inspection_price=None,
            )
            april.service_months = [4, 10]
            self._contract(session, number="физлицо", client_type="individual")
            session.commit()

            result = run_auto_contract_packages(
                session, date(2026, 9, 1), self._generator
            )
            self.assertEqual(
                set(result.ready),
                {"Объект ежемесячный", "Объект март-сентябрь"},
            )
            self.assertNotIn(
                "Объект апрель-октябрь", {row.label for row in result.skipped}
            )

    def test_sole_proprietor_payer_creates_package(self):
        with Session(self.engine) as session:
            self._contract(
                session,
                number="ИП-плательщик",
                client_type="sole_proprietor",
            )
            session.commit()

            result = run_auto_contract_packages(
                session, date(2026, 9, 1), self._generator
            )

            self.assertEqual(result.ready, ("Объект ИП-плательщик",))
            self.assertIsNotNone(session.scalar(select(ContractPeriod.id)))
            self.assertIsNotNone(session.scalar(select(InspectionReport.id)))

    def test_individual_payer_is_reported_as_unsupported(self):
        with Session(self.engine) as session:
            self._contract(session, number="физлицо", client_type="individual")
            session.commit()

            result = run_auto_contract_packages(
                session, date(2026, 9, 1), self._generator
            )

            self.assertEqual(result.ready, ())
            self.assertEqual(
                result.skipped[0].reasons,
                ("тип плательщика не поддерживается",),
            )
            self.assertIn(
                "Объект физлицо: тип плательщика не поддерживается",
                format_auto_package_summary(result),
            )

    def test_treatment_creates_four_document_manifest_and_is_idempotent(self):
        with Session(self.engine) as session:
            contract = self._contract(session)
            assert contract.object is not None
            session.add(
                Treatment(
                    object=contract.object,
                    chemicals_used=[
                        {
                            "chemical_name": "ТЕСТ препарат",
                            "quantity_used": "1.000",
                            "unit": "л",
                        }
                    ],
                    performed_at=datetime(2026, 9, 20, 12, 0),
                    performed_by="Артём",
                )
            )
            session.add(
                Treatment(
                    object=contract.object,
                    chemicals_used=[
                        {
                            "chemical_name": "ТЕСТ второй препарат",
                            "quantity_used": "2.000",
                            "unit": "кг",
                        }
                    ],
                    performed_at=datetime(2026, 9, 10, 12, 0),
                    performed_by="Алексей",
                )
            )
            session.commit()

            first = run_auto_contract_packages(
                session, date(2026, 9, 1), self._generator
            )
            second = run_auto_contract_packages(
                session, date(2026, 9, 1), self._generator
            )
            period = session.scalar(select(ContractPeriod))
            report = session.scalar(select(InspectionReport))
            assert period is not None and report is not None
            self.assertEqual(first.ready, ("Объект ТЕСТ-01",))
            self.assertEqual(second.ready, ())
            self.assertEqual(len(period.file_manifest), 4)
            self.assertEqual(period.preparations, "ТЕСТ препарат, ТЕСТ второй препарат")
            self.assertEqual(period.price_snapshot, Decimal("3000.00"))
            self.assertEqual(period.treatment_price_snapshot, Decimal("5000.00"))
            self.assertNotEqual(period.invoice_number, period.treatment_invoice_number)
            self.assertEqual(report.inspection_date, date(2026, 9, 20))

    def test_telegram_summary_contains_only_safe_object_results(self):
        with Session(self.engine) as session:
            self._contract(session, number="готов")
            self._contract(session, number="без-цены", inspection_price=None)
            session.commit()
            result = run_auto_contract_packages(
                session, date(2026, 9, 1), self._generator
            )
            text = format_auto_package_summary(result)
            self.assertIn("Пакеты за 09.2026", text)
            self.assertIn("Объект готов", text)
            self.assertIn("Объект без-цены: не задана цена обследования", text)
            self.assertNotIn("ТЕСТ адрес", text)
            self.assertNotIn("ТЕСТ клиент", text)

    def test_first_day_daily_report_sends_auto_package_summary_via_mock(self):
        with Session(self.engine) as session:
            self._contract(session, number="готов")
            self._contract(session, number="без-цены", inspection_price=None)
            session.commit()
        messages: list[str] = []

        def sender(_token: str, _chat_id: int, message: str) -> bool:
            messages.append(message)
            return True

        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "test-token", "OWNER_TG_ID": "123"},
            clear=True,
        ):
            send_daily_report(
                self.engine,
                "auto",
                datetime(2026, 10, 1, 9, 10, tzinfo=ZoneInfo("Europe/Moscow")),
                sender=sender,
                auto_package_generator=self._generator,
            )

        self.assertEqual(len(messages), 1)
        self.assertIn("Пакеты за 09.2026", messages[0])
        self.assertIn("Объект готов", messages[0])
        self.assertIn("не задана цена обследования", messages[0])
        self.assertNotIn("ТЕСТ адрес", messages[0])


if __name__ == "__main__":
    unittest.main()
