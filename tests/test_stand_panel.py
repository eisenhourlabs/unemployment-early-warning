"""
Tests for the Overview's "Where things stand" panel and "What changed this week" (review WP7, 2026-11).
Run them with:
    python -m unittest discover -s tests -v

Everything here uses made-up data (a fabricated live_latest.json and made-up weekly claims), so the results do
not depend on this week's figures.

What they check:
  (a) all green: statuses Low / Falling / Green, the "all green" sentence, and the closing line "No measure is
      more than half-way ...";
  (b) new claims at +17% of their low (amber): "Rising", the frequency sentence, and new claims listed first
      among the measures;
  (c) continuing claims +25% on a year ago (red): "Rising fast" and the severity-red sentence;
  (d) the provisional "event under way" flag on: cell 3's replacement sentence and the first "What it means" row;
  (e) "What changed": a week with initial claims up 30,000 starts with a line ending "(a larger move than usual).";
      an ordinary week starts with "Nothing unusual this week."
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "site"))
import overview  # noqa: E402

WEEKS = pd.date_range("2024-01-06", periods=120, freq="W-SAT")


def claims_table(ic4_last=200_000.0, cc4_now=1_700_000.0, cc4_year_ago=1_900_000.0) -> pd.DataFrame:
    """Made-up weekly claims: a flat 4-week average of 200,000 with a small wiggle, the last week set to ic4_last;
    continuing claims' 4-week average cc4_year_ago 52 weeks before the end and cc4_now at the end."""
    rng = np.random.default_rng(1)
    ic4 = 200_000 + rng.normal(0, 2_000, len(WEEKS)).round()
    ic4[:-1] = np.maximum(ic4[:-1], 200_000)      # the low of the previous 52 weeks is exactly 200,000
    ic4[-1] = ic4_last
    cc4 = np.full(len(WEEKS), cc4_now)
    cc4[-53] = cc4_year_ago
    return pd.DataFrame({"week_ended": WEEKS, "ic_sa_4wk": ic4, "cc_sa_4wk": cc4,
                         "source_initial": "ETA 539", "source_continued": "ETA 539"})


UR = pd.Series([4.1] * 24, index=pd.date_range("2024-11-01", periods=24, freq="MS"))


def live(v_sahm=0.0, v_ic=0.0, v_cc=-0.10, colour="green", text="2%", event=None) -> dict:
    """A minimal live_latest.json with only the fields the panel reads."""
    out = {
        "asof": "2026-11-12", "run_at": "2026-11-12 21:00 UTC",
        "inputs": {"initial_claims_week": f"{WEEKS[-1]:%Y-%m-%d}", "continuing_claims_week": f"{WEEKS[-1]:%Y-%m-%d}",
                   "unemployment_month": "2026-10-01"},
        "triggers": {"rows": [{"id": "sahm", "value": v_sahm, "colour": "green"},
                              {"id": "claims_vs_low", "value": v_ic, "colour": "green"},
                              {"id": "cont_claims_yoy", "value": v_cc, "colour": "green"}]},
        "score": {"colour": colour, "display": {"6": {"text": text, "words": False}}, "base_rates": {"6": 0.153},
                  "contributions": [{"input": "temp_help", "contribution": 0.29,
                                     "sentence": "Temporary-help jobs grew only 1.4% over six months"},
                                    {"input": "claims_low", "contribution": -1.0, "sentence": "New claims are low"}],
                  "drivers": [], "previous": {"display": {"text": text}, "colour": colour}, "change_pt": 0.1,
                  "first_live_run": False, "live_runs": 3},
    }
    if event:
        out["event_state"] = event
    return out


class StandPanel(unittest.TestCase):
    def test_a_all_green(self):
        p = overview.stand_panel(live(), claims_table(), UR)
        self.assertEqual([c["badge"] for c in p["cells"]], ["Low", "Falling", "Green · 2%"])
        self.assertEqual(p["meaning"], overview.MEANING["all_green"])
        self.assertTrue(p["closing"].startswith("No measure is more than half-way to a warning level."))
        self.assertLessEqual(len(p["watch"]), 3)
        self.assertIn("Temporary-help jobs", p["watch"][0]["bold"])          # the input pushing risk up comes first
        self.assertIn("Chance of a claims jump or unemployment rise within 6 months: 2% (usual: 15%).",
                      p["cells"][2]["main"])

    def test_b_new_claims_amber(self):
        p = overview.stand_panel(live(v_ic=0.17), claims_table(ic4_last=234_000), UR)
        self.assertEqual(p["cells"][0]["badge"], "Rising")
        self.assertEqual(p["cells"][0]["colour"], "amber")
        self.assertIn("That is the warning zone.", p["cells"][0]["main"])
        self.assertEqual(p["meaning"], overview.MEANING["freq_amber"])
        self.assertEqual(p["meaning_colour"], "amber")
        measures = [w["bold"] for w in p["watch"] if w["meter"] is not None]
        self.assertTrue(measures[0].startswith("New claims, 4-week average"), measures)
        self.assertEqual(p["cells"][0]["small"], "Red at about 250,000 a week.")

    def test_c_continuing_claims_red(self):
        p = overview.stand_panel(live(v_cc=0.25), claims_table(cc4_now=2_000_000, cc4_year_ago=1_600_000), UR)
        self.assertEqual(p["cells"][1]["badge"], "Rising fast")
        self.assertEqual(p["cells"][1]["colour"], "red")
        self.assertEqual(p["meaning"], overview.MEANING["sev_red"])
        self.assertIn("25% more than a year ago", p["cells"][1]["main"])
        self.assertIn("past its warning level", p["closing"])

    def test_d_event_flag(self):
        p = overview.stand_panel(live(event={"under_way": True, "provisional_start": "2026-09"}), claims_table(), UR)
        self.assertEqual(p["cells"][2]["main"], "A deterioration is under way since Sep 2026 (provisional). The score "
                                                "now shows the chance of a further, new event.")
        self.assertTrue(p["meaning"].startswith(overview.MEANING["freq_red"]))

    def test_duration_words(self):
        words = [overview.duration_watch(v)["word"] for v in (-0.01, 0.0, 0.099, 0.10, 0.199, 0.20)]
        self.assertEqual(words, ["Falling", "Steady", "Steady", "Rising", "Rising", "Rising fast"])


class WhatChanged(unittest.TestCase):
    def series(self, last_ic_jump):
        rng = np.random.default_rng(2)
        ic = pd.Series(200_000 + rng.normal(0, 8_000, len(WEEKS)).round(-3), index=WEEKS)
        ic.iloc[-1] = ic.iloc[-2] + last_ic_jump
        ic4 = ic.rolling(4).mean().bfill()
        cc = pd.Series(1_700_000 + rng.normal(0, 20_000, len(WEEKS)).round(-3), index=WEEKS)
        cc.iloc[-1] = cc.iloc[-2] + 5_000
        return {"ICSA": ic, "IC4WSA": ic4, "CCSA": cc}

    def run_week(self, jump):
        claims = claims_table()
        return overview.what_changed(claims, datetime(2026, 11, 12, tzinfo=timezone.utc), live(), prev={},
                                     series=self.series(jump), ur_news=False)

    def test_large_move(self):
        out = self.run_week(30_000)
        self.assertTrue(out[0].endswith("(a larger move than usual)."), out[0])
        self.assertTrue(out[0].startswith("SA initial claims rose 30,000"), out[0])
        self.assertLessEqual(len(out), 4)

    def test_ordinary_week(self):
        out = self.run_week(1_000)
        self.assertEqual(out[0], "Nothing unusual this week.")
        self.assertEqual(out[1], "The early-warning score is 2%, green, unchanged.")
        self.assertTrue(out[2].startswith("Weekly claims moved within their normal range: new claims"), out[2])
        self.assertLessEqual(len(out), 4)


if __name__ == "__main__":
    unittest.main()
