"""
Tests for the Duration watch backtest (review WP5, src/model/severity_watch.py). Run with:
    python -m unittest discover -s tests -v

What they check (made-up weekly continuing claims):
  1. a series rising 25% a year is in band "red"; a flat one "green"; a falling one "falling";
  2. the outcomes are blank for the last 12 months (month t+12 not observed yet).
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "model"))
import severity_watch as sw  # noqa: E402

WEEKS = pd.date_range("2000-01-01", periods=52 * 4, freq="W-SAT")


def weekly(growth_per_year: float) -> pd.DataFrame:
    t = np.arange(len(WEEKS)) / 52
    return pd.DataFrame({"week_ended": WEEKS, "CCSA": 1_500_000 * (1 + growth_per_year) ** t})


class Bands(unittest.TestCase):
    def last_band(self, growth):
        return sw.band_of(sw.monthly_cc_yoy(weekly(growth)).dropna().iloc[-1])

    def test_rising_fast_is_red(self):
        self.assertEqual(self.last_band(0.25), "red")

    def test_flat_is_green(self):
        self.assertEqual(self.last_band(0.0), "green")

    def test_falling(self):
        self.assertEqual(self.last_band(-0.05), "falling")

    def test_outcomes_blank_for_last_12_months(self):
        idx = pd.date_range("2000-01-01", periods=36, freq="MS")
        levels = pd.DataFrame({c: np.linspace(1, 40, 36) for c, _ in sw.OUTCOMES.values()}, index=idx)
        out = sw.outcomes_frame(levels)
        self.assertTrue(out.iloc[-12:].isna().all().all())
        self.assertTrue(out.iloc[:-12].notna().all().all())


if __name__ == "__main__":
    unittest.main()
