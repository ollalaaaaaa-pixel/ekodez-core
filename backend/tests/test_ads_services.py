import os
import tempfile
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet
from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.ads.attribution import attribute_lead, set_manual_attribution
from app.ads.importer import import_ads_file
from app.ads.metrics import ads_metrics
from app.ads.parsers import AdsParseError
from app.models import (
    AdCallLog,
    AdImportRun,
    AdSpend,
    Base,
    Lead,
    Notification,
    Transaction,
)
from app.security.ad_phone_hash import phone_hmac
from app.security.pii import encrypt_pii


class AdsServicesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.key = Fernet.generate_key().decode("ascii")

    def tearDown(self):
        self.engine.dispose()

    def test_import_is_idempotent_and_never_stores_plain_phone(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "calls.csv"
            path.write_text(
                "Дата звонка;Телефон\n08.09.2026;+79215551234\n", encoding="utf-8"
            )
            with Session(self.engine) as session:
                import_ads_file(session, "2gis", path, pii_key=self.key)
                session.commit()
                import_ads_file(session, "2gis", path, pii_key=self.key)
                session.commit()
                self.assertEqual(len(session.scalars(select(AdCallLog)).all()), 1)
                self.assertEqual(len(session.scalars(select(AdImportRun)).all()), 2)
                self.assertEqual(
                    [row.kind for row in session.scalars(select(Notification)).all()],
                    ["ads_import_ok", "ads_import_ok"],
                )
                self.assertNotIn(
                    "79215551234", repr(session.scalars(select(AdCallLog)).all())
                )

    def test_spend_upsert_updates_values_without_duplicate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "spend.csv"
            header = (
                "Кампания;Начало периода;Конец периода;Расход;"
                "Показы;Клики;Конверсии\n"
            )
            path.write_text(
                header + "Поиск;01.09.2026;07.09.2026;1000;100;10;1\n",
                encoding="utf-8",
            )
            with Session(self.engine) as session:
                import_ads_file(session, "yandex_direct", path, pii_key=self.key)
                session.commit()
                path.write_text(
                    header + "Поиск;01.09.2026;07.09.2026;1200;120;12;2\n",
                    encoding="utf-8",
                )
                import_ads_file(session, "yandex_direct", path, pii_key=self.key)
                session.commit()
                rows = session.scalars(select(AdSpend)).all()
                self.assertEqual(len(rows), 1)
                self.assertEqual(Decimal(rows[0].spend), Decimal("1200.00"))

    def test_import_uses_explicit_report_period_end(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "september.csv"
            path.write_text(
                "Кампания;Начало периода;Конец периода;Расход\n"
                "Поиск;01.09.2026;30.09.2026;1000\n",
                encoding="utf-8",
            )
            with Session(self.engine) as session:
                summary = import_ads_file(
                    session, "yandex_direct", path, pii_key=self.key
                )
                session.commit()
                run = session.scalar(select(AdImportRun))
                self.assertEqual(summary.period, "2026-09-01..2026-09-30")
                self.assertEqual(run.period_end, date(2026, 9, 30))

    def test_import_error_creates_safe_error_journal_and_notification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "broken.csv"
            path.write_text("foo;bar\n1;2\n", encoding="utf-8")
            with Session(self.engine) as session:
                with self.assertRaises(AdsParseError):
                    import_ads_file(session, "2gis", path, pii_key=self.key)
                session.commit()
                run = session.scalar(select(AdImportRun))
                notice = session.scalar(select(Notification))
                self.assertEqual(run.status, "error")
                self.assertEqual(notice.kind, "ads_import_error")
                self.assertNotIn("phone", repr(notice.payload).lower())
                self.assertNotIn("broken.csv", run.source_file)
                self.assertNotIn("foo", run.error or "")

    def test_import_masks_sensitive_values_in_journal_and_notification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "client-+79215551234@example.ru.csv"
            path.write_text(
                "Дата звонка;Телефон\n08.09.2026;+79215551234\n", encoding="utf-8"
            )
            with Session(self.engine) as session:
                summary = import_ads_file(session, "2gis", path, pii_key=self.key)
                session.commit()
                run = session.scalar(select(AdImportRun))
                notice = session.scalar(select(Notification))
                stored = repr((run.source_file, run.error, notice.payload, summary))
                self.assertNotIn("79215551234", stored)
                self.assertNotIn("example.ru", stored)
                self.assertRegex(run.source_file, r"^file-[0-9a-f]{12}\.csv$")

    def test_all_import_formats_and_error_payloads_store_no_plain_pii(self):
        phone = "+79215559876"
        name = "ТестовыйКлиент"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            csv_path = root / f"{name}-{phone}.csv"
            csv_path.write_text(
                f"Дата звонка;Телефон\n08.09.2026;{phone}\n", encoding="utf-8"
            )
            xlsx_path = root / f"{name}-{phone}.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            assert sheet is not None
            sheet.append(["Дата звонка", "Телефон"])
            sheet.append(["09.09.2026", phone])
            workbook.save(xlsx_path)
            xls_path = root / f"{name}-{phone}.xls"
            xls_path.write_text(
                f"<table><tr><th>Дата звонка</th><th>Телефон</th></tr>"
                f"<tr><td>10.09.2026</td><td>{phone}</td></tr></table>",
                encoding="utf-8",
            )
            broken = root / f"{name}-{phone}-broken.csv"
            broken.write_text("bad;header\n1;2\n", encoding="utf-8")
            with Session(self.engine) as session:
                for path in (csv_path, xlsx_path, xls_path):
                    import_ads_file(session, "2gis", path, pii_key=self.key)
                    session.commit()
                with self.assertRaises(AdsParseError):
                    import_ads_file(session, "2gis", broken, pii_key=self.key)
                session.commit()
                stored = repr(
                    (
                        [
                            (row.phone_hash, row.source_file)
                            for row in session.scalars(select(AdCallLog)).all()
                        ],
                        [
                            (row.source_file, row.error)
                            for row in session.scalars(select(AdImportRun)).all()
                        ],
                        [
                            row.payload
                            for row in session.scalars(select(Notification)).all()
                        ],
                    )
                )
                self.assertNotIn("79215559876", stored)
                self.assertNotIn(name, stored)

    def test_utm_phone_match_manual_and_metrics(self):
        now = datetime(2026, 9, 8, 12, tzinfo=UTC)
        with (
            patch.dict(os.environ, {"PII_FERNET_KEY": self.key}),
            Session(self.engine) as session,
        ):
            utm = Lead(
                source="site",
                status="new",
                amount=Decimal("0"),
                performed_by="Артём",
                created_at=now,
                utm_source="yandex",
                utm_campaign="search",
            )
            matched = Lead(
                source="phone",
                status="new",
                amount=Decimal("0"),
                performed_by="Артём",
                created_at=now,
                encrypted_pii=encrypt_pii({"phone": "+79215551234"}),
            )
            session.add_all([utm, matched])
            session.flush()
            session.add(
                AdCallLog(
                    platform="2gis",
                    call_date=now,
                    phone_hash=phone_hmac("89215551234"),
                    source_file="calls.csv",
                )
            )
            session.add(
                AdSpend(
                    platform="yandex_direct",
                    campaign="search",
                    period_start=date(2026, 9, 1),
                    period_end=date(2026, 9, 30),
                    spend=Decimal("1000"),
                    impressions=100,
                    clicks=10,
                    conversions=1,
                )
            )
            session.flush()
            self.assertEqual(attribute_lead(session, utm, now).method, "utm")
            self.assertEqual(
                attribute_lead(session, matched, now).method, "phone_match"
            )
            set_manual_attribution(session, matched, None, now)
            self.assertEqual(attribute_lead(session, matched, now).method, "manual")
            session.add(
                Transaction(
                    source="manual",
                    operation_date=date(2026, 9, 9),
                    amount=Decimal("4000"),
                    currency="RUB",
                    kind="income",
                    review_required=False,
                    needs_review=False,
                    lead_id=utm.id,
                )
            )
            session.commit()
            row = ads_metrics(session, date(2026, 9, 1), date(2026, 9, 30))[0]
            self.assertEqual(row.cpl, Decimal("1000.00"))
            self.assertEqual(row.romi, Decimal("300.00"))

    def test_phone_match_checks_each_semicolon_separated_phone(self):
        now = datetime(2026, 9, 8, 12, tzinfo=UTC)
        with (
            patch.dict(os.environ, {"PII_FERNET_KEY": self.key}),
            Session(self.engine) as session,
        ):
            lead = Lead(
                source="phone",
                status="new",
                amount=Decimal("0"),
                performed_by="Артём",
                created_at=now,
                encrypted_pii=encrypt_pii({"phone": "+79210000001; +79215551234"}),
            )
            session.add(lead)
            session.add(
                AdCallLog(
                    platform="2gis",
                    call_date=now,
                    phone_hash=phone_hmac("+79215551234"),
                    source_file="file-deadbeef0000.csv",
                )
            )
            session.flush()
            self.assertEqual(attribute_lead(session, lead, now).platform, "2gis")

    def test_metrics_separate_platform_and_campaign_and_use_period_income(self):
        with Session(self.engine) as session:
            session.add_all(
                [
                    AdSpend(
                        platform="2gis",
                        campaign="card",
                        period_start=date(2026, 9, 1),
                        period_end=date(2026, 9, 30),
                        spend=Decimal("3000"),
                        impressions=0,
                        clicks=0,
                        conversions=0,
                    ),
                    Lead(
                        source="2gis",
                        status="new",
                        amount=Decimal("0"),
                        performed_by="Артём",
                        created_at=datetime(2026, 9, 5, tzinfo=UTC),
                        attributed_platform="2gis",
                        attribution_method="manual",
                    ),
                    Lead(
                        source="2gis",
                        status="new",
                        amount=Decimal("0"),
                        performed_by="Артём",
                        created_at=datetime(2026, 9, 6, tzinfo=UTC),
                        attributed_platform="2gis",
                        attribution_method="utm",
                        utm_campaign="card",
                    ),
                    Lead(
                        source="2gis",
                        status="new",
                        amount=Decimal("0"),
                        performed_by="Артём",
                        created_at=datetime(2026, 8, 25, tzinfo=UTC),
                        attributed_platform="2gis",
                        attribution_method="utm",
                        utm_campaign="card",
                    ),
                ]
            )
            session.flush()
            leads = session.scalars(select(Lead).order_by(Lead.id)).all()
            session.add_all(
                [
                    Transaction(
                        source="manual",
                        operation_date=date(2026, 8, 31),
                        amount=Decimal("9000"),
                        currency="RUB",
                        kind="income",
                        review_required=False,
                        needs_review=False,
                        lead_id=leads[2].id,
                    ),
                    Transaction(
                        source="manual",
                        operation_date=date(2026, 9, 10),
                        amount=Decimal("6000"),
                        currency="RUB",
                        kind="income",
                        review_required=False,
                        needs_review=False,
                        lead_id=leads[1].id,
                    ),
                ]
            )
            session.commit()
            rows = ads_metrics(session, date(2026, 9, 1), date(2026, 9, 30))
            platform = next(row for row in rows if row.campaign == "Без кампании")
            campaign = next(row for row in rows if row.campaign == "card")
            self.assertEqual(platform.leads, 1)
            self.assertEqual(platform.revenue, Decimal("0.00"))
            self.assertEqual(campaign.leads, 1)
            self.assertEqual(campaign.revenue, Decimal("6000.00"))

    def test_metric_null_reasons_are_explicit(self):
        with Session(self.engine) as session:
            session.add(
                AdSpend(
                    platform="2gis",
                    campaign="card",
                    period_start=date(2026, 9, 1),
                    period_end=date(2026, 9, 30),
                    spend=Decimal("1000"),
                    impressions=0,
                    clicks=0,
                    conversions=0,
                )
            )
            session.commit()
            rows = ads_metrics(session, date(2026, 9, 1), date(2026, 9, 30))
            campaign = next(row for row in rows if row.campaign == "card")
            self.assertIsNone(campaign.cpl)
            self.assertEqual(campaign.cpl_reason, "no_attributed_leads")
            self.assertIsNone(campaign.romi)
            self.assertEqual(campaign.romi_reason, "no_attributed_leads")

    def test_notification_payload_has_no_unapproved_pii(self):
        from app.ads.notifications import create_notification

        with Session(self.engine) as session:
            row = create_notification(
                session,
                "ads_import_ok",
                {
                    "platform": "2gis",
                    "source_file": "calls.csv",
                    "rows": 1,
                    "phone": "+79215551234",
                },
                datetime.now(UTC),
            )
            self.assertNotIn("phone", row.payload)
            self.assertNotIn("79215551234", repr(row.payload))
            self.assertNotIn("calls.csv", repr(row.payload))

            alert = create_notification(
                session,
                "ads_alert",
                {
                    "platform": "2gis",
                    "reason": "client +79215551234",
                    "period": "2026-09-01-2026-09-07",
                    "metrics": {
                        "spend": "100.00",
                        "leads": 1,
                        "campaign": "client +79215551234",
                    },
                },
                datetime.now(UTC),
            )
            self.assertNotIn("79215551234", repr(alert.payload))
            self.assertNotIn("campaign", repr(alert.payload))

    def test_metrics_prorate_overlapping_period_and_serialize_nulls(self):
        with Session(self.engine) as session:
            session.add(
                AdSpend(
                    platform="2gis",
                    campaign="card",
                    period_start=date(2026, 9, 1),
                    period_end=date(2026, 9, 10),
                    spend=Decimal("1000.00"),
                    impressions=0,
                    clicks=0,
                    conversions=0,
                )
            )
            session.commit()
            row = ads_metrics(session, date(2026, 9, 1), date(2026, 9, 5))[0]
            self.assertEqual(row.spend, Decimal("500.00"))
            self.assertIsNone(row.cpl)
            self.assertIsNone(row.romi)
            self.assertEqual(row.romi_reason, "no_attributed_leads")
            self.assertEqual(row.json()["cpl"], None)


if __name__ == "__main__":
    unittest.main()
