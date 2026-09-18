"""Regression tests for the two Problem B Poka-Yoke designs."""
import unittest

import tools


class SpecialtyPokaYokeTests(unittest.TestCase):
    def test_valid_specialty_matches_referral(self):
        result = tools.check_referral_criteria("OPH", "REF-5602")
        self.assertEqual(result["band"], "routine")

    def test_unknown_specialty_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "specialty must be one of"):
            tools.check_referral_criteria("XYZ", "REF-5602")

    def test_valid_but_wrong_specialty_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "does not match referral"):
            tools.check_referral_criteria("CARD", "REF-5602")


class SlotWindowPokaYokeTests(unittest.TestCase):
    def test_valid_explicit_window_returns_only_legal_slots(self):
        slots = tools.get_clinic_slots(
            "OPH", "routine", **{
                "from": "2026-09-09",
                "to": "2026-11-04",
            })
        self.assertTrue(slots)
        self.assertTrue(all(s["band"] == "routine" for s in slots))
        self.assertTrue(all("2026-09-09" <= s["date"] <= "2026-11-04"
                            for s in slots))

    def test_missing_window_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires window field"):
            tools.get_clinic_slots("OPH", "routine")

    def test_invented_band_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "band must be one of"):
            tools.get_clinic_slots(
                "OPH", "priority", **{
                    "from": "2026-09-09",
                    "to": "2026-11-04",
                })

    def test_reversed_window_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must not be later"):
            tools.get_clinic_slots(
                "OPH", "routine", **{
                    "from": "2026-11-04",
                    "to": "2026-09-09",
                })

    def test_invalid_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "valid YYYY-MM-DD"):
            tools.get_clinic_slots(
                "OPH", "routine", **{
                    "from": "2026-09-31",
                    "to": "2026-11-04",
                })


if __name__ == "__main__":
    unittest.main()
