"""
Tests for src/model/score_uncertainty.py (review WP1, 2026-11). Run them with:
    python -m unittest discover -s tests -v

On a 48-month toy history (2000-2003, an event month every 6th month):
  1. a score equal to the outcome (p = y) has skill 1.0;
  2. a score equal to the base rate (p = base) has skill 0.0;
  3. two bootstrap runs with the same seed give identical percentiles;
  4. the longest run of months at 20% or more is found with its first and last month.
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "model"))
import score_uncertainty as su  # noqa: E402


def toy() -> pd.DataFrame:
    months = pd.date_range("2000-01-01", periods=48, freq="MS")
    y = np.array([1 if i % 6 == 0 else 0 for i in range(48)])
    return pd.DataFrame({"y": y, "base": 0.15, "perfect": y.astype(float)}, index=months)


class Skill(unittest.TestCase):
    def test_perfect_score_has_skill_one(self):
        t = toy()
        self.assertAlmostEqual(su.skill(t["perfect"], t["y"], t["base"])[2], 1.0)

    def test_base_rate_has_skill_zero(self):
        t = toy()
        self.assertAlmostEqual(su.skill(t["base"], t["y"], t["base"])[2], 0.0)

    def test_bootstrap_is_reproducible(self):
        t = toy()
        t["noisy"] = (0.5 * t["y"] + 0.1).clip(0, 1)
        a = su.bootstrap_skill(t, "noisy", draws=500)
        b = su.bootstrap_skill(t, "noisy", draws=500)
        self.assertEqual(np.quantile(a, 0.05), np.quantile(b, 0.05))
        self.assertEqual(np.quantile(a, 0.95), np.quantile(b, 0.95))

    def test_longest_run(self):
        p = pd.Series([0.1, 0.3, 0.25, 0.1, 0.2, 0.6, 0.5, 0.1],
                      index=pd.date_range("2022-01-01", periods=8, freq="MS"))
        self.assertEqual(su.longest_run(p, 0.20), (3, "2022-05", "2022-07"))


if __name__ == "__main__":
    unittest.main()
