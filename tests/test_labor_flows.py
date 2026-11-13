"""
Tests for the labour-flow measures (review WP5 Part D, src/transforms/labor_flows.py). Run with:
    python -m unittest discover -s tests -v

What they check:
  1. the job-finding formula on made-up numbers: U = 100 then 100 with 30 newly unemployed -> 1 - 70/100 = 30%;
     a missing month leaves the rate blank (no October 2025 survey);
  2. on the real data file (skipped if it has not been built): the 3-month job-finding rate lies between 15% and
     50% in every month from 1990 on, leaving out April-December 2020 (the rate was 50-65% in the 1950s-60s and
     about 11% in mid-2020, both genuine), and openings per unemployed lie between 0.1 and 2.5.
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "transforms"))
import labor_flows  # noqa: E402

FILE = ROOT / "data" / "processed" / "labor_flows_monthly.csv"


class Formula(unittest.TestCase):
    def test_job_finding(self):
        idx = pd.date_range("2025-08-01", periods=4, freq="MS")
        u = pd.Series([100.0, 100.0, np.nan, 100.0], index=idx)
        s = pd.Series([30.0, 30.0, np.nan, 30.0], index=idx)
        f = labor_flows.job_finding(u, s)
        self.assertAlmostEqual(f.iloc[1], 30.0)
        self.assertTrue(np.isnan(f.iloc[2]) and np.isnan(f.iloc[3]))


@unittest.skipUnless(FILE.exists(), "labor_flows_monthly.csv not built")
class RealData(unittest.TestCase):
    def setUp(self):
        self.d = pd.read_csv(FILE, parse_dates=["month"]).set_index("month")

    def test_job_finding_range(self):
        j = self.d.job_finding_rate_3m.dropna()
        j = j[(j.index >= "1990-01-01") & ((j.index < "2020-04-01") | (j.index > "2020-12-01"))]
        self.assertTrue(((j >= 15) & (j <= 50)).all(), j[(j < 15) | (j > 50)])

    def test_openings_per_unemployed_range(self):
        v = self.d.vacancies_per_unemployed.dropna()
        self.assertTrue(((v >= 0.1) & (v <= 2.5)).all())
        self.assertEqual(f"{v.index[0]:%Y-%m}", "2000-12")


if __name__ == "__main__":
    unittest.main()
