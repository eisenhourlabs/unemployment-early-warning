"""
Tests for review WP3 (2026-11): the FOMC marker for next year and the forecast coverage by regime. Run with:
    python -m unittest discover -s tests -v

  1. fomc_marker.fomc_next: with next year's UNRATEMD value it returns year + 1, the value, the marker date, our
     12-month middle value and the gap; without it, None.
  2. forecast_regimes.evaluate on a 6-row toy backtest: regimes by the stated rules (during an event once it has
     lasted 3+ months; before an event; other), coverage, misses above / below and the error ratio.
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "model"))
import fomc_marker  # noqa: E402
import forecast_regimes as fr  # noqa: E402

FAN = {"horizons": [{"horizon": 3, "median": 4.0, "target_period": "2027-01-01"},
                    {"horizon": 12, "median": 3.7, "target_period": "2027-10-01"}]}


class FomcNext(unittest.TestCase):
    def test_with_next_year(self):
        s = pd.Series([4.1, 4.2], index=pd.to_datetime(["2026-01-01", "2027-01-01"]))
        n = fomc_marker.fomc_next(s, 2026, FAN)
        self.assertEqual((n["year"], n["value"], n["marker_date"]), (2027, 4.2, "2027-11-15"))
        self.assertEqual((n["our_12m_median"], n["our_12m_period"]), (3.7, "2027-10-01"))
        self.assertAlmostEqual(n["gap"], 0.5)

    def test_without_next_year(self):
        s = pd.Series([4.1, None], index=pd.to_datetime(["2026-01-01", "2027-01-01"]))
        self.assertIsNone(fomc_marker.fomc_next(s, 2026, FAN))
        self.assertIsNone(fomc_marker.fomc_next(s.iloc[:1], 2026, FAN))


class Regimes(unittest.TestCase):
    def setUp(self):
        # One event, Jan 2008 - Dec 2009 (start month counts as month 1)
        self.ev = pd.DataFrame({"event": ["12"], "start": pd.to_datetime(["2008-01-01"]),
                                "end": pd.to_datetime(["2009-12-01"])})
        origins = ["2007-06-01", "2007-09-01", "2008-02-01", "2008-06-01", "2008-09-01", "2005-01-01"]
        self.bt = pd.DataFrame({
            "origin": pd.to_datetime(origins), "target": "ur", "horizon": 6,
            "in_progress": [False, False, True, True, True, False],
            "event_starts_within_h": [True, True, False, False, False, False],
            "covid_window": False,
            "level_at_origin": [5.0] * 6,
            "center": [5.0, 5.0, 5.0, 6.0, 7.0, 5.0],
            "q10": [4.0] * 3 + [5.0, 6.0, 4.0], "q25": [4.5] * 3 + [5.5, 6.5, 4.5],
            "q75": [5.5] * 3 + [6.5, 7.5, 5.5], "q90": [6.0] * 3 + [7.0, 8.0, 6.0],
            "realized": [5.2, 5.8, 5.5, 7.5, 7.0, 5.0]})

    def test_regimes(self):
        bt = fr.add_regime(self.bt, self.ev)
        self.assertEqual(list(bt.age), [0, 0, 2, 6, 9, 0])
        self.assertEqual(list(bt.regime), ["before an event", "before an event", "other", "during an event",
                                           "during an event", "other"])

    def test_measures(self):
        out = fr.evaluate(self.bt, self.ev).set_index("regime")
        d = out.loc["during an event"]
        self.assertEqual(d.origins, 2)
        self.assertAlmostEqual(d.cover80, 0.5)            # 7.5 is above q90 7.0; 7.0 is inside 6.0-8.0
        self.assertAlmostEqual(d.above_q90, 0.5)
        self.assertAlmostEqual(d.mean_error, 0.75)         # (1.5 + 0) / 2
        b = out.loc["before an event"]
        self.assertEqual((b.origins, b.cover80, b.cover50), (2, 1.0, 0.5))
        a = out.loc["all"]
        self.assertEqual(a.origins, 6)
        # errors vs. the middle: 0.2, 0.8, 0.5, 1.5, 0, 0; vs. no change: 0.2, 0.8, 0.5, 2.5, 2.0, 0
        self.assertAlmostEqual(a.rmse_ratio, ((0.04 + 0.64 + 0.25 + 2.25) / (0.04 + 0.64 + 0.25 + 6.25 + 4.0)) ** 0.5)


if __name__ == "__main__":
    unittest.main()
