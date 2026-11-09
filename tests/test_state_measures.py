"""
Tests for the state measures (Phase 4 stage 4a). Run them with:
    python -m unittest discover -s tests -v

What they check:
  1. weekly_measures: claims = regular state UI only (work-share equivalents left out); 4-week averages; the year-on-year change compares
     the same weeks 52 weeks earlier; continued weeks are dated by the week they reflect.
  2. diffusion: unweighted, covered-employment weighted and weights-weighted shares on a small made-up example,
     including a state with no value (the shares then use the states that have one).
  3. weighted_mean re-scales the present weights to sum to 1.
  4. The 12-month-low gap skips a missing month.
  5. The committed weights (config/state_weights.csv) sum to 1, and match the private file when it is on this PC
     (skipped in the cloud, which has no private file).
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "transforms"))
import make_state_weights  # noqa: E402
import state_measures as sm  # noqa: E402


def fake_ar539(state: str, weeks: int, ic, cw, ce=1_000_000, ws_ic=0, ws_cw=0) -> pd.DataFrame:
    """A made-up ar539 extract: one row per week from 2020-01-04, with constant or listed claims."""
    dates = pd.date_range("2020-01-04", periods=weeks, freq="7D")
    ic = np.broadcast_to(ic, weeks)
    cw = np.broadcast_to(cw, weeks)
    return pd.DataFrame({"state": state, "week_ended": dates.strftime("%Y-%m-%d"),
                         "reflected_week_ended": (dates - pd.Timedelta(days=7)).strftime("%Y-%m-%d"),
                         "ic_state_ui": ic, "ic_stc_workshare_equiv": ws_ic,
                         "cw_state_ui": cw, "cw_stc_workshare_equiv": ws_cw, "covered_employment": ce})


class WeeklyMeasureTests(unittest.TestCase):
    def test_rates_averages_and_year_on_year(self):
        # Claims 1,000 a week for a year, then 1,200: after 4 weeks of the higher level the change is +20%.
        ic = [1000] * 52 + [1200] * 8
        w = sm.weekly_measures(fake_ar539("TX", 60, ic, 5000, ws_ic=0, ws_cw=0))
        w = w.dropna(subset=["initial_claims"]).reset_index(drop=True)   # row i = filing week i
        self.assertTrue(np.isnan(w.ic_yoy_pct.iloc[51]))          # no year-earlier value yet
        self.assertAlmostEqual(w.initial_claims_4wk.iloc[55], 1200)
        self.assertAlmostEqual(w.ic_yoy_pct.iloc[55], 20.0)
        self.assertAlmostEqual(w.ic_rate.iloc[0], 0.1)             # 1,000 / 1,000,000 x 100
        self.assertTrue(np.isnan(w.ic_rate_4wk.iloc[2]))           # needs 4 weeks

    def test_work_share_excluded_and_continued_weeks_dated_by_reflected_week(self):
        w = sm.weekly_measures(fake_ar539("OH", 6, 100, 900, ws_ic=5, ws_cw=10))
        self.assertTrue((w.initial_claims.dropna() == 100).all())     # regular state UI only
        self.assertTrue((w.continued_weeks.dropna() == 900).all())
        # The first continued-weeks row belongs to the week BEFORE the first filing week.
        first_cc = w.dropna(subset=["continued_weeks"]).week_ended.min()
        self.assertEqual(first_cc, pd.Timestamp("2019-12-28"))
        self.assertAlmostEqual(w.cc_rate.dropna().iloc[0], 0.09)


class DiffusionTests(unittest.TestCase):
    def setUp(self):
        week = pd.Timestamp("2021-01-02")
        # Three states: A up 25% (big), B up 10%, C up 40% (small); D has no value this week.
        self.weekly = pd.DataFrame({
            "state": ["AA", "BB", "CC", "DD"], "week_ended": week,
            "ic_yoy_pct": [25.0, 10.0, 40.0, np.nan],
            "covered_employment": [600.0, 300.0, 100.0, 1000.0]})
        self.w = pd.Series({"AA": 0.2, "BB": 0.5, "CC": 0.1, "DD": 0.2})

    def run_diffusion(self):
        orig = sm.measure_areas
        sm.measure_areas = lambda: ["AA", "BB", "CC", "DD"]
        try:
            return sm.diffusion(self.weekly, self.w).iloc[0]
        finally:
            sm.measure_areas = orig

    def test_three_weightings(self):
        d = self.run_diffusion()
        self.assertEqual(d.areas_reported, 3)
        self.assertEqual(d.areas_up, 2)
        self.assertAlmostEqual(d.diffusion_unweighted_pct, 200 / 3)
        self.assertAlmostEqual(d.diffusion_ce_weighted_pct, 70.0)        # (600 + 100) / 1000; DD's jobs left out
        self.assertAlmostEqual(d.diffusion_weighted_pct, 0.3 / 0.8 * 100)  # DD's weight re-scaled away
        self.assertAlmostEqual(d.weights_present, 0.8)

    def test_threshold_is_inclusive(self):
        self.weekly.loc[1, "ic_yoy_pct"] = 20.0
        self.assertEqual(self.run_diffusion().areas_up, 3)


class HelperTests(unittest.TestCase):
    def test_weighted_mean_rescales(self):
        v = pd.DataFrame({"AA": [1.0, 1.0], "BB": [3.0, np.nan]})
        mean, present = sm.weighted_mean(v, pd.Series({"AA": 0.25, "BB": 0.75}))
        self.assertAlmostEqual(mean.iloc[0], 2.5)
        self.assertAlmostEqual(mean.iloc[1], 1.0)
        self.assertAlmostEqual(present.iloc[1], 0.25)

    def test_gap_is_state_sahm_convention(self):
        """Phase 4 review Gate 2: 3-month average minus the lowest 3-month average of the previous 12 months
        (2 of 3 months allowed: Oct 2025 missing), identical to the national trigger's realtime.sahm()."""
        idx = pd.period_range("2024-01", "2025-12", freq="M")
        vals = [4.0] * 12 + [4.0] * 6 + [4.2, 4.4, 4.6, np.nan, 4.8, 5.0]
        s = pd.Series(vals, index=idx)
        avg3, low, gap = sm.gap_to_12m_low(s)
        self.assertAlmostEqual(avg3.iloc[-1], 4.9)          # (4.8 + 5.0) / 2: October missing
        self.assertAlmostEqual(low.iloc[-1], 4.0)
        self.assertAlmostEqual(gap.iloc[-1], 0.9)
        self.assertTrue(np.isnan(low.iloc[11]))             # needs 11 of the previous 12 months
        sys.path.insert(0, str(ROOT / "src" / "model"))
        from realtime import sahm
        self.assertAlmostEqual(gap.iloc[-1], sahm(pd.Series(vals)))


class ReviewGateTests(unittest.TestCase):
    """Phase 4 review: 'vs. normal' and the weighted contributions."""

    def test_vs_normal_median_of_prior_three_years_skipping_pandemic(self):
        weeks = pd.date_range("2019-01-05", periods=52 * 4 + 1, freq="7D")       # last week: 2022-12-31
        rate = pd.Series(2.0, index=weeks)                                       # 2021 after June: 2.0
        rate[weeks < "2020-03-01"] = 1.0                                         # before the pandemic: 1.0
        rate[(weeks >= "2020-03-01") & (weeks <= "2021-06-30")] = 9.0            # pandemic window: ignored
        rate[weeks.year == 2022] = 1.0
        rate[pd.Timestamp("2022-01-01")] = 2.0
        df = pd.DataFrame({"state": "AA", "week_ended": weeks, "ic_rate_4wk": rate.values})
        # same weeks 52/104/156 weeks earlier: 2022-01-01 (2.0), 2021-01-02 (pandemic: dropped), 2020-01-04 (1.0)
        # normal = median(2.0, 1.0) = 1.5; latest 1.0 -> -33.3% vs. normal
        self.assertAlmostEqual(sm.vs_normal(df).iloc[-1], (1.0 / 1.5 - 1) * 100)
        df.loc[df.week_ended == weeks[-1], "ic_rate_4wk"] = 1.8
        self.assertAlmostEqual(sm.vs_normal(df).iloc[-1], 20.0)

    def test_contributions_sum_to_weighted_change(self):
        weeks = pd.date_range("2024-01-06", periods=53, freq="7D")
        rows = []
        for st, r0, r1 in [("AA", 1.0, 1.5), ("BB", 2.0, 2.0), ("CC", 1.0, 0.5)]:
            for i, wk in enumerate(weeks):
                rows.append({"state": st, "week_ended": wk, "ic_rate_4wk": r0 if i < 52 else r1})
        w = pd.Series({"AA": 0.5, "BB": 0.3, "CC": 0.2})
        c = sm.contributions(pd.DataFrame(rows), w)
        last = c[c.week_ended == weeks[-1]].set_index("state").contribution_pct
        base = 0.5 * 1.0 + 0.3 * 2.0 + 0.2 * 1.0
        self.assertAlmostEqual(last["AA"], 0.5 * 0.5 / base * 100)
        self.assertAlmostEqual(last["CC"], 0.2 * -0.5 / base * 100)
        weighted_change = ((0.5 * 1.5 + 0.3 * 2.0 + 0.2 * 0.5) / base - 1) * 100
        self.assertAlmostEqual(last.sum(), weighted_change)


class WeightFileTests(unittest.TestCase):
    def test_committed_weights_sum_to_one(self):
        w = pd.read_csv(ROOT / "config" / "state_weights.csv", comment="#")
        self.assertAlmostEqual(w.weight.sum(), 1.0, places=9)
        self.assertTrue((w.weight > 0).all())
        self.assertTrue(set(w.state) <= set(sm.measure_areas()))

    def test_rounding_sums_exactly(self):
        shares = make_state_weights.share_weights(pd.Series([1, 1, 1]))
        self.assertAlmostEqual(shares.sum(), 1.0, places=12)
        self.assertEqual(sorted(shares.round(6)), [0.333333, 0.333333, 0.333334])

    @unittest.skipUnless((ROOT / "internal" / "state_weights_private.csv").exists(), "private file only on Troy's PC")
    def test_committed_weights_match_private_file(self):
        expected = make_state_weights.build(pd.read_csv(ROOT / "internal" / "state_weights_private.csv", comment="#"))
        committed = pd.read_csv(ROOT / "config" / "state_weights.csv", comment="#")
        pd.testing.assert_frame_equal(committed.reset_index(drop=True), expected.reset_index(drop=True),
                                      check_exact=False, atol=1e-9)


if __name__ == "__main__":
    unittest.main()
