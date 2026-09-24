import unittest

from app.security.ad_phone_hash import PhoneHashError, phone_hmac


class AdPhoneHashTest(unittest.TestCase):
    def test_same_phone_formats_match_within_one_key(self):
        key = "test-pii-key-one"

        plus_seven = phone_hmac("+7 (921) 555-12-34", key=key)
        leading_eight = phone_hmac("8 921 555 12 34", key=key)

        self.assertEqual(plus_seven, leading_eight)
        self.assertEqual(len(plus_seven), 64)
        self.assertNotIn("79215551234", plus_seven)

    def test_different_keys_cannot_match_the_same_phone(self):
        first = phone_hmac("+7 921 555-12-34", key="test-pii-key-one")
        second = phone_hmac("+7 921 555-12-34", key="test-pii-key-two")

        self.assertNotEqual(first, second)

    def test_invalid_phone_is_rejected(self):
        with self.assertRaises(PhoneHashError):
            phone_hmac("not-a-phone", key="test-pii-key-one")


if __name__ == "__main__":
    unittest.main()
