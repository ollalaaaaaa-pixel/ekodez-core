import os
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet

from app.security.pii import (
    decrypt_pii,
    encrypt_pii,
    mask_address,
    mask_name,
    mask_phone,
    mask_text,
    pii_status,
)


class PiiMaskingTest(unittest.TestCase):
    def test_phone_keeps_four_leading_and_four_trailing_digits(self):
        self.assertEqual(mask_phone("89214725000"), "8921***5000")
        self.assertEqual(mask_phone("+7 (921) 472-50-00"), "7921***5000")
        self.assertEqual(mask_phone("123"), "***")

    def test_address_keeps_only_city_segment(self):
        self.assertEqual(
            mask_address("г. Архангельск, ул. Ленина, 10, кв. 5"),
            "г. Архангельск, ***",
        )
        self.assertEqual(mask_address("Архангельск"), "Архангельск, ***")
        self.assertEqual(mask_address("Архангельск ул. Ленина 10"), "Архангельск, ***")

    def test_name_keeps_only_first_name(self):
        self.assertEqual(mask_name("Котлов Артём Васильевич"), "Артём")
        self.assertEqual(mask_name("Иван Петров"), "Иван")
        self.assertEqual(mask_name(""), "")

    def test_text_replaces_exact_pii_without_leaking_original_values(self):
        source = (
            "Имя клиента: Котлов Артём Васильевич\n"
            "Телефон: 89214725000\n"
            "Адрес: г. Архангельск, ул. Ленина, 10, кв. 5"
        )
        masked = mask_text(
            source,
            name="Котлов Артём Васильевич",
            phone="89214725000",
            address="г. Архангельск, ул. Ленина, 10, кв. 5",
        )
        self.assertNotIn("Котлов", masked)
        self.assertNotIn("4725000", masked)
        self.assertNotIn("Ленина", masked)
        self.assertIn("Артём", masked)
        self.assertIn("8921***5000", masked)
        self.assertIn("г. Архангельск, ***", masked)

    def test_fernet_round_trip_and_degraded_status(self):
        key = Fernet.generate_key().decode("ascii")
        full = {
            "client_name": "Котлов Артём Васильевич",
            "phone": "89214725000",
            "address": "г. Архангельск, ул. Ленина, 10",
            "raw_text": "синтетическая заявка",
            "comment": "перезвонить после 18:00",
        }
        with patch.dict(os.environ, {"PII_FERNET_KEY": key}, clear=False):
            encrypted = encrypt_pii(full)
            self.assertIsInstance(encrypted, str)
            self.assertNotIn("Котлов", encrypted or "")
            self.assertEqual(decrypt_pii(encrypted), full)
            self.assertEqual(pii_status(), "ok")

        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(encrypt_pii(full))
            self.assertEqual(pii_status(), "degraded")


if __name__ == "__main__":
    unittest.main()
