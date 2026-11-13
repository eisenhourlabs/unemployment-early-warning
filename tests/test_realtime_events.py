"""
Tests for the real-time "event under way" rule (review WP4, src/model/realtime_events.py). Run with:
    python -m unittest discover -s tests -v

What they check:
  1. On data/model/triggers_monthly.csv, the 2008 event is under way from 2008-05 and stays so to at least 2010-05.
  2. The latest month is not under way (November 2026 data).
  3. A made-up series: one on-month then 5 off-months is still under way; with 6 off-months it is not.
  4. The current-month reading replaces the month it stands for.
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "model"))
import realtime_events as rte  # noqa: E402


def toy(on_flags):
    idx = pd.date_range("2020-01-01", periods=len(on_flags), freq="MS")
    return pd.DataFrame({"ur": [False] * len(on_flags), "claims": on_flags}, index=idx)


class RealData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legs = rte.month_end_on()

    def test_2008(self):
        s = rte.state_by_month(self.legs)
        self.assertFalse(s.loc["2008-04-01", "under_way"])
        months = s.loc["2008-05-01":"2010-05-01"]
        self.assertTrue(months.under_way.all())
        self.assertEqual(f"{months.start.iloc[0]:%Y-%m}", "2008-05")
        st = rte.event_state(self.legs, until="2008-05-01")
        self.assertTrue(st["under_way"] and st["provisional_start"] == "2008-05" and st["months_since_start"] == 1)

    def test_latest_not_under_way(self):
        self.assertFalse(rte.event_state(self.legs)["under_way"])


class Toy(unittest.TestCase):
    def test_five_quiet_months_still_under_way(self):
        st = rte.event_state(toy([True] + [False] * 5))
        self.assertTrue(st["under_way"])
        self.assertEqual(st["provisional_start"], "2020-01")
        self.assertEqual(st["months_since_start"], 6)
        self.assertEqual(st["leg"], "claims")

    def test_six_quiet_months_ends_it(self):
        self.assertFalse(rte.event_state(toy([True] + [False] * 6))["under_way"])

    def test_current_month(self):
        legs = toy([False] * 4)
        st = rte.event_state(legs, current={"month": "2020-04-01", "ur": True, "claims": False})
        self.assertTrue(st["under_way"])
        self.assertEqual((st["provisional_start"], st["leg"]), ("2020-04", "unemployment"))


if __name__ == "__main__":
    unittest.main()
