"""
Unit tests for review WP9 items after the meeting:
  C7  whatif_table: today, the values at the asked steps, and the peak with "after N months";
  C8  the trigger rule names the triggers; live.py and the site use the same sentence, and an old numbered rule
      from a live_latest.json written before the change is reworded;
  C14 colour_range: diverging scales are centred on 0; sequential scales run from the 5th to the 95th percentile.
Run: python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "site"))
sys.path.insert(0, str(ROOT / "src" / "model"))
import common  # noqa: E402
import states  # noqa: E402


def fake_stress():
    path = lambda peak_at, peak: [{"period": f"p{k}", "level": 4.0 + (peak - 4.0) * min(k, peak_at) / peak_at}
                                  for k in range(25)]
    return {"latest_period": "p0", "level": 4.0,
            "scenarios": {"2001-type (#9)": path(18, 6.0), "2008-type (#12)": path(21, 9.0)}}


class WhatifTable(unittest.TestCase):
    def test_rows_and_peak(self):
        t = common.whatif_table(fake_stress(), [3, 6, 12], "months", 1, 1, "%", "Unemployment rate, %")
        self.assertEqual(t["head"], ["Today", "+3 months", "+6 months", "+12 months", "Peak"])
        self.assertEqual([r["name"] for r in t["rows"]], ["2001-type", "2008-type"])
        self.assertEqual(t["rows"][0]["cells"][0], "4.0%")
        self.assertEqual(t["rows"][0]["peak"], "6.0% after 18 months")
        self.assertEqual(t["rows"][1]["peak"], "9.0% after 21 months")
        self.assertIn("A what-if, not a forecast.", t["note"])

    def test_multiplier_for_claims(self):
        s = {"scenarios": {"2001-type (#9)": [{"period": "w0", "level": 0.127}, {"period": "w1", "level": 0.2}]}}
        t = common.whatif_table(s, [13], "weeks", 100, 1, "", "Initial claims rate")
        self.assertEqual(t["rows"][0]["cells"], ["12.7", "—"])        # beyond the path: a dash
        self.assertEqual(t["rows"][0]["peak"], "20.0 after 1 week")


class TriggerNames(unittest.TestCase):
    def test_same_rule_in_model_and_site(self):
        import live  # noqa: E402  (src/model/live.py)
        self.assertEqual(live.TRIGGER_RULE, common.TRIGGER_RULE)
        self.assertNotRegex(common.TRIGGER_RULE, r"trigger \d")
        self.assertIn("the Sahm indicator, new claims or continuing claims", common.TRIGGER_RULE)

    def test_old_rule_reworded(self):
        old = {"triggers": {"rule": "Red if trigger 1, 2 or 4 is red; amber if one of 1, 2, 4 is amber or red and "
                                    "another panel trigger is amber or red; otherwise green."}}
        common.reword_live(old)
        self.assertEqual(old["triggers"]["rule"], common.TRIGGER_RULE)


class ColourRange(unittest.TestCase):
    def test_diverging_centred(self):
        lo, hi = states.colour_range(list(range(-10, 31)) + [None], "diverging")
        self.assertEqual(lo, -hi)
        self.assertAlmostEqual(hi, 28.0)

    def test_sequential_quantiles(self):
        lo, hi = states.colour_range([float(x) for x in range(0, 101)], "sequential")
        self.assertAlmostEqual(lo, 5.0)
        self.assertAlmostEqual(hi, 95.0)


if __name__ == "__main__":
    unittest.main()
