import unittest
from typing import cast

from sqlalchemy import Boolean, String, Table, Uuid
from sqlalchemy.schema import ColumnDefault

from app.models import Transaction


class BankImportModelTest(unittest.TestCase):
    def test_transaction_exposes_import_audit_fields(self):
        columns = cast(Table, Transaction.__table__).c

        self.assertEqual(cast(String, columns.source_hash.type).length, 64)
        self.assertTrue(columns.source_hash.nullable)
        self.assertEqual(cast(String, columns.doc_number.type).length, 50)
        self.assertEqual(cast(String, columns.counterparty_inn.type).length, 20)
        self.assertIsInstance(columns.import_batch_id.type, Uuid)
        self.assertEqual(cast(String, columns.source_filename.type).length, 255)
        self.assertIsInstance(columns.needs_review.type, Boolean)
        self.assertFalse(columns.needs_review.nullable)
        self.assertIsNotNone(columns.needs_review.default)
        default = cast(ColumnDefault, columns.needs_review.default)
        self.assertFalse(default.arg)

    def test_source_hash_has_one_unique_index(self):
        indexes = [
            index
            for index in cast(Table, Transaction.__table__).indexes
            if [column.name for column in index.columns] == ["source_hash"]
        ]

        self.assertEqual(len(indexes), 1)
        self.assertTrue(indexes[0].unique)


if __name__ == "__main__":
    unittest.main()
