"""
Tests for the shutdown fallback (Phase 4 stage 4c, src/fetchers/dol_state_fallback.py). Run with:
    python -m unittest discover -s tests -v

Made-up example with three areas (A, B, C) over three weeks, so every number can be checked by hand:
  1. area_claims adds work-sharing equivalents to regular state UI and keeps a non-reporting area blank.
  2. estimate_nsa: carry forward uses the area's last value; scaled multiplies it by the reporting areas' change.
  3. to_sa divides by factor / 100; error_pct.
  4. overdue: the release is due Thursday 9:30 am ET after the week ends.
  5. estimate_rows estimates only overdue weeks after the latest official week; merge keeps the better estimate;
     fill_officials fills the official value and error once DOL publishes.
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "fetchers"))
import dol_state_fallback as fb  # noqa: E402

W1, W2, W3 = pd.Timestamp("2026-10-17"), pd.Timestamp("2026-10-24"), pd.Timestamp("2026-10-31")


def fake_ar539() -> pd.DataFrame:
    rows = []
    # (area, week, regular state UI, work-share equivalent); C does not report in W3
    data = {("A", W1): (100, 0), ("B", W1): (200, 10), ("C", W1): (50, 0),
            ("A", W2): (120, 0), ("B", W2): (220, 10), ("C", W2): (60, 0),
            ("A", W3): (180, 0), ("B", W3): (330, 0), ("C", W3): (None, None)}
    for (area, week), (ui, ws) in data.items():
        rows.append({"state": area, "week_ended": week.strftime("%Y-%m-%d"),
                     "reflected_week_ended": (week - pd.Timedelta(days=7)).strftime("%Y-%m-%d"),
                     "ic_state_ui": ui, "ic_stc_workshare_equiv": ws,
                     "cw_state_ui": None if ui is None else ui * 10, "cw_stc_workshare_equiv": 0})
    return pd.DataFrame(rows)


class TestEstimator(unittest.TestCase):
    def setUp(self):
        self.ic, self.cc = fb.area_claims(fake_ar539())

    def test_area_claims(self):
        self.assertEqual(self.ic.at[W1, "B"], 210)            # 200 regular + 10 work-share
        self.assertTrue(pd.isna(self.ic.at[W3, "C"]))         # C did not report in W3
        self.assertEqual(self.cc.index.max(), W2)             # continued weeks dated by the week they reflect

    def test_carry_forward(self):
        nsa, filled = fb.estimate_nsa(self.ic, W3, [], "carry")
        self.assertEqual(filled, ["C"])
        self.assertEqual(nsa, 180 + 330 + 60)                  # C carried forward from W2

    def test_scaled(self):
        # reporting areas A, B went from 120 + 230 = 350 in W2 to 180 + 330 = 510 in W3; C: 60 x 510 / 350
        nsa, _ = fb.estimate_nsa(self.ic, W3, [], "scaled")
        self.assertAlmostEqual(nsa, 510 + 60 * 510 / 350)

    def test_drop_listed_area(self):
        # an area that did report can still be treated as missing (the validation does this)
        nsa, filled = fb.estimate_nsa(self.ic, W2, ["A"], "carry")
        self.assertEqual(filled, ["A"])
        self.assertEqual(nsa, 100 + 230 + 60)

    def test_sa_and_error(self):
        self.assertAlmostEqual(fb.to_sa(1000, 125.0), 800.0)
        self.assertAlmostEqual(fb.error_pct(102, 100), 2.0)

    def test_overdue(self):
        week = pd.Timestamp("2026-10-31")                      # released Thursday Nov 5, 8:30 am ET
        et = fb.EASTERN
        self.assertFalse(fb.overdue(week, datetime(2026, 11, 5, 9, 0, tzinfo=et)))
        self.assertTrue(fb.overdue(week, datetime(2026, 11, 5, 9, 30, tzinfo=et)))
        self.assertTrue(fb.overdue(week, datetime(2026, 11, 6, 7, 0, tzinfo=et)))

    def test_rows_merge_and_official(self):
        factors = pd.DataFrame({"ic_sf": [100.0, 100.0, 125.0], "cc_sf": [100.0, 100.0, 100.0]},
                               index=[W1, W2, W3])
        official = {"ic": pd.Series([360.0, 410.0], index=[W1, W2]), "cc": pd.Series([3600.0], index=[W1 - pd.Timedelta(days=7)])}
        early = datetime(2026, 11, 5, 9, 0, tzinfo=fb.EASTERN)
        self.assertEqual([r for r in fb.estimate_rows(self.ic, self.cc, factors, official, early)
                          if r["measure"] == "ic"], [])        # not yet overdue: no estimate
        late = datetime(2026, 11, 6, 7, 0, tzinfo=fb.EASTERN)
        rows = [r for r in fb.estimate_rows(self.ic, self.cc, factors, official, late) if r["measure"] == "ic"]
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual((r["week_ended"], r["areas_reported"], r["missing_areas"]), (W3, 2, "C"))
        expected_nsa = 510 + 60 * 510 / 350
        self.assertEqual(r["estimate_nsa"], round(expected_nsa))
        self.assertEqual(r["estimate_sa"], round(expected_nsa / 1.25))
        est = fb.merge(pd.DataFrame(columns=fb.COLUMNS), rows)
        # a later run with more areas reporting replaces the open estimate
        better = dict(r, areas_reported=3, estimate_sa=999)
        est = fb.merge(est, [better])
        self.assertEqual(est.estimate_sa.iloc[0], 999)
        # DOL publishes W3: official value and error filled in, log line written
        official["ic"] = pd.concat([official["ic"], pd.Series([1000.0], index=[W3])])
        est, lines = fb.fill_officials(est, official, late)
        self.assertEqual(est.official_sa.iloc[0], 1000)
        self.assertAlmostEqual(est.error_pct.iloc[0], -0.1)
        self.assertEqual(len(lines), 1)

    def test_provisional_archive_rules(self):
        """A run on estimated claims gets its own archive name; official figures for the same week trigger a new run."""
        sys.path.insert(0, str(ROOT / "src" / "model"))
        import live
        inputs = {"initial_claims_week": "2026-10-31", "unemployment_month": "2026-10-01"}
        asof = pd.Timestamp("2026-11-09")
        self.assertTrue(live.archive_name(asof, inputs, provisional=True).endswith("_provisional.json"))
        self.assertFalse(live.archive_name(asof, inputs).endswith("_provisional.json"))
        prov = ("2026-11-06_ic2026-10-31_ur2026-10_provisional.json", "2026-10-31", "2026-10-01")
        self.assertTrue(live.has_new_inputs(inputs, prov, provisional_now=False))     # official now in: re-run
        self.assertFalse(live.has_new_inputs(inputs, prov, provisional_now=True))     # still estimated: no re-run
        off = ("2026-11-06_ic2026-10-31_ur2026-10.json", "2026-10-31", "2026-10-01")
        self.assertFalse(live.has_new_inputs(inputs, off))

    def test_unknown_method(self):
        with self.assertRaises(ValueError):
            fb.estimate_nsa(self.ic, W3, [], "average")


if __name__ == "__main__":
    unittest.main()
