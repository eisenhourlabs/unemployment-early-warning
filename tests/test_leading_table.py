"""
Unit tests for the Leading page summary table (review WP6, Part B):
  (a) risk_pct: a latest value equal to the historical maximum gives 100; equal to the minimum gives a value near 0;
  (b) the labels: 80+ "High", 60 to under 80 "Above normal", 40 to under 60 "Normal", under 40 "Low";
  (c) the 6-month change form (quits rate) and the year-ago form (permits);
  (d) the yield curve is ranked on the lowest monthly average of the past 18 months.
Run: python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "site"))
import leading  # noqa: E402


class RiskPct(unittest.TestCase):
    def setUp(self):
        self.hist = pd.Series(np.arange(1.0, 401.0))   # 400 distinct values

    def test_maximum_is_100(self):
        self.assertEqual(leading.risk_pct(self.hist, self.hist.max()), 100.0)

    def test_minimum_is_near_zero(self):
        self.assertLess(leading.risk_pct(self.hist, self.hist.min()), 1.0)

    def test_direction_down_turns_the_series(self):
        # risk_direction "down": the lowest raw value is the riskiest, so ranking -x puts it at 100
        x = self.hist
        self.assertEqual(leading.risk_pct(-x, -x.min()), 100.0)

    def test_labels(self):
        self.assertEqual(leading.risk_label(80), "High")
        self.assertEqual(leading.risk_label(79.9), "Above normal")
        self.assertEqual(leading.risk_label(60), "Above normal")
        self.assertEqual(leading.risk_label(59.9), "Normal")
        self.assertEqual(leading.risk_label(40), "Normal")
        self.assertEqual(leading.risk_label(39.9), "Low")
        self.assertEqual(leading.risk_label(0), "Low")


class Forms(unittest.TestCase):
    def test_six_month_change(self):
        idx = pd.date_range("2020-01-01", periods=12, freq="MS")
        s = pd.Series(np.arange(12) * 0.1 + 2.0, index=idx)
        out = leading.page_series(s, "JTSQUR")
        self.assertEqual(out.index[0], pd.Timestamp("2020-07-01"))
        self.assertAlmostEqual(out.iloc[-1], 0.6)

    def test_year_ago_change(self):
        idx = pd.date_range("2020-01-01", periods=13, freq="MS")
        s = pd.Series([100.0] * 12 + [110.0], index=idx)
        out = leading.page_series(s, "PERMIT")
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out.iloc[-1], 10.0)

    def test_yield_curve_uses_18_month_low(self):
        idx = pd.date_range("2020-01-01", "2022-12-31", freq="D")
        s = pd.Series(1.0, index=idx)
        s[(s.index >= "2021-03-01") & (s.index < "2021-04-01")] = -1.0   # one inverted month
        ranked = leading.ranking_series(s, "T10Y3M", "daily")
        # 18 months after March 2021 (through Aug 2022) the low is still -1; from Sep 2022 it is back to +1
        self.assertAlmostEqual(ranked[pd.Timestamp("2022-08-01")], -1.0)
        self.assertAlmostEqual(ranked[pd.Timestamp("2022-09-01")], 1.0)


if __name__ == "__main__":
    unittest.main()
