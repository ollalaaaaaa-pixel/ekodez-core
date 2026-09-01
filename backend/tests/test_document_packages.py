import re
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

from app.document_packages import (
    DocumentTemplateError,
    build_month_package,
    resolve_package_file,
)


class DocumentPackageTest(unittest.TestCase):
    @staticmethod
    def _template_values(template_dir: Path) -> dict[str, str]:
        tokens: set[str] = set()
        for path in template_dir.glob("*.docx"):
            with zipfile.ZipFile(path) as archive:
                xml = "\n".join(
                    archive.read(name).decode("utf-8", "ignore")
                    for name in archive.namelist()
                    if name.endswith(".xml")
                )
            tokens.update(re.findall(r"\{\{([^{}]+)\}\}", xml))
        return {token: f"ТЕСТ {token}" for token in tokens}

    def test_paid_package_is_versioned_and_has_no_placeholders(self):
        template_dir = Path(__file__).parents[2] / "docs" / "templates"
        values = self._template_values(template_dir)
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            first = build_month_package(
                template_dir=template_dir,
                output_root=output_root,
                object_name="ТЕСТ / Хостел",
                period_month=date(2026, 9, 1),
                paid_service_due=True,
                values=values,
            )
            second = build_month_package(
                template_dir=template_dir,
                output_root=output_root,
                object_name="ТЕСТ / Хостел",
                period_month=date(2026, 9, 1),
                paid_service_due=True,
                values=values,
            )

            self.assertEqual(first.version, 1)
            self.assertEqual(second.version, 2)
            self.assertEqual(len(first.files), 3)
            self.assertTrue(first.directory.is_relative_to(output_root))
            self.assertTrue(all(len(item.sha256) == 64 for item in first.files))
            for item in first.files:
                self.assertGreater(item.size, 0)
                with zipfile.ZipFile(first.directory / item.name) as archive:
                    xml = "\n".join(
                        archive.read(name).decode("utf-8", "ignore")
                        for name in archive.namelist()
                        if name.endswith(".xml")
                    )
                self.assertNotRegex(xml, r"\{\{[^{}]+\}\}")

    def test_inspection_only_package_contains_one_document(self):
        template_dir = Path(__file__).parents[2] / "docs" / "templates"
        values = self._template_values(template_dir)
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = build_month_package(
                template_dir=template_dir,
                output_root=Path(temp_dir),
                object_name="ТЕСТ Осмотр",
                period_month=date(2026, 8, 1),
                paid_service_due=False,
                values=values,
            )
        self.assertEqual([item.kind for item in manifest.files], ["inspection"])

    def test_missing_value_leaves_no_partial_version(self):
        template_dir = Path(__file__).parents[2] / "docs" / "templates"
        values = self._template_values(template_dir)
        values.pop("CONTRACT_NUM")
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            with self.assertRaises(DocumentTemplateError):
                build_month_package(
                    template_dir=template_dir,
                    output_root=output_root,
                    object_name="ТЕСТ Ошибка",
                    period_month=date(2026, 9, 1),
                    paid_service_due=True,
                    values=values,
                )
            self.assertEqual(list(output_root.rglob("v*")), [])

    def test_download_path_cannot_escape_output_root(self):
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            self.assertRaises(DocumentTemplateError),
        ):
            resolve_package_file(
                output_root=Path(temp_dir),
                object_name="ТЕСТ",
                period_month=date(2026, 9, 1),
                version=1,
                file_name="..\\..\\..\\..\\секрет.txt",
            )


if __name__ == "__main__":
    unittest.main()
