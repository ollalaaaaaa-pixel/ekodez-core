import csv
import os
import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

from app.ads.parsers import AdsParseError, parse_ads_file


class AdsParsersTest(unittest.TestCase):
    def test_csv_spend_headers_are_detected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "direct.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow(["Отчет Яндекс Директа"])
                writer.writerow(
                    [
                        "Кампания",
                        "Начало периода",
                        "Конец периода",
                        "Расход (руб.)",
                        "Показы",
                        "Клики",
                        "Конверсии",
                    ]
                )
                writer.writerow(
                    ["Поиск", "01.09.2026", "07.09.2026", "1 234,50", 1000, 25, 3]
                )

            parsed = parse_ads_file(path, "yandex_direct", pii_key="test-key")

            self.assertEqual(len(parsed.spend_rows), 1)
            row = parsed.spend_rows[0]
            self.assertEqual(row.campaign, "Поиск")
            self.assertEqual(row.period_start, date(2026, 9, 1))
            self.assertEqual(row.spend, Decimal("1234.50"))
            self.assertEqual(
                (row.impressions, row.clicks, row.conversions), (1000, 25, 3)
            )

    def test_xlsx_call_phone_is_replaced_by_hmac(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "calls.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            assert sheet is not None
            sheet.append(["Дата звонка", "Телефон"])
            sheet.append([datetime(2026, 9, 8, 12, 30), "+7 (921) 555-12-34"])
            workbook.save(path)

            parsed = parse_ads_file(path, "2gis", pii_key="test-key")

            self.assertEqual(len(parsed.call_rows), 1)
            call = parsed.call_rows[0]
            self.assertEqual(call.call_date, datetime(2026, 9, 8, 12, 30))
            self.assertEqual(len(call.phone_hash), 64)
            self.assertFalse(hasattr(call, "phone"))
            self.assertNotIn("79215551234", repr(parsed))

    def test_html_xls_is_supported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "business.xls"
            path.write_text(
                "<table><tr><th>Кампания</th><th>Дата</th><th>Расход</th>"
                "<th>Показы</th><th>Переходы</th><th>Целевые действия</th></tr>"
                "<tr><td>Карты</td><td>08.09.2026</td><td>500,00</td>"
                "<td>200</td><td>10</td><td>2</td></tr></table>",
                encoding="utf-8",
            )

            parsed = parse_ads_file(path, "yandex_business", pii_key="test-key")

            self.assertEqual(parsed.spend_rows[0].period_start, date(2026, 9, 8))
            self.assertEqual(parsed.spend_rows[0].period_end, date(2026, 9, 8))
            self.assertEqual(parsed.spend_rows[0].clicks, 10)

    def test_monthly_report_without_end_uses_last_day_of_september(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "monthly.csv"
            path.write_text(
                "Отчет за месяц сентябрь 2026\n"
                "Кампания;Начало периода;Расход\n"
                "Поиск;01.09.2026;3000\n",
                encoding="utf-8",
            )
            row = parse_ads_file(path, "yandex_direct").spend_rows[0]
            self.assertEqual(row.period_start, date(2026, 9, 1))
            self.assertEqual(row.period_end, date(2026, 9, 30))

    def test_weekly_marker_and_daily_date_keep_their_ranges(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            weekly = Path(temp_dir) / "weekly.csv"
            weekly.write_text(
                "Кампания;Начало периода;Гранулярность;Расход\n"
                "Поиск;14.09.2026;неделя;700\n",
                encoding="utf-8",
            )
            self.assertEqual(
                parse_ads_file(weekly, "yandex_direct").spend_rows[0].period_end,
                date(2026, 9, 20),
            )
            daily = Path(temp_dir) / "daily.csv"
            daily.write_text(
                "Кампания;Дата;Расход\nПоиск;14.09.2026;100\n",
                encoding="utf-8",
            )
            self.assertEqual(
                parse_ads_file(daily, "yandex_direct").spend_rows[0].period_end,
                date(2026, 9, 14),
            )

    def test_empty_and_unknown_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            empty = Path(temp_dir) / "empty.csv"
            empty.write_text("", encoding="utf-8")
            unknown = Path(temp_dir) / "unknown.csv"
            unknown.write_text("foo,bar\n1,2\n", encoding="utf-8")

            with self.assertRaises(AdsParseError):
                parse_ads_file(empty, "2gis", pii_key="test-key")
            with self.assertRaises(AdsParseError):
                parse_ads_file(unknown, "2gis", pii_key="test-key")

    def test_missing_environment_key_rejects_call_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "calls.csv"
            path.write_text(
                "Дата звонка;Телефон\n08.09.2026;+79215551234\n",
                encoding="utf-8",
            )
            with (
                patch.dict(os.environ, {}, clear=True),
                self.assertRaises(AdsParseError),
            ):
                parse_ads_file(path, "2gis")


if __name__ == "__main__":
    unittest.main()
