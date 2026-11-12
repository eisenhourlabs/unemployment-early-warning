"""
Tests for the score's display words (review WP2, 2026-11). Run them with:
    python -m unittest discover -s tests -v

What they check:
  1. live.score_display: under 35% a whole percent; 35-50% "Elevated"; 50% and above "High" (never
     "More likely than not"); both verbal bands keep the number in the tooltip and add the testing sentence.
     Thresholds come from the frozen model, as in a live run.
  2. common.reword_live: a live_latest.json written before the change (old label, old tooltip, old comparison
     label, old rule wording) is shown with the new words, and applying it twice changes nothing more.
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "model"))
sys.path.insert(0, str(ROOT / "src" / "site"))
import live  # noqa: E402
import common  # noqa: E402

FROZEN = json.loads(sorted((ROOT / "data" / "model" / "frozen").glob("model_*.json"))[-1].read_text(encoding="utf-8"))


def display_settings() -> dict:
    """The frozen model's display thresholds (the same dictionary live.py passes to score_display)."""
    def find(d):
        if isinstance(d, dict):
            if "more_likely_from" in d:
                return d
            for v in d.values():
                found = find(v)
                if found:
                    return found
        return None
    return find(FROZEN)


class ScoreDisplayTests(unittest.TestCase):
    def setUp(self):
        self.disp = display_settings()
        self.assertIsNotNone(self.disp, "frozen model has the display settings")

    def test_bands(self):
        self.assertEqual(live.score_display(0.018, self.disp)["text"], "2%")
        self.assertEqual(live.score_display(0.40, self.disp)["text"], "Elevated")
        high = live.score_display(0.76, self.disp)
        self.assertEqual(high["text"], "High")
        self.assertTrue(high["words"])
        self.assertIn("about 76%", high["tooltip"])
        self.assertIn("roughly half the time", high["tooltip"])
        self.assertIn("roughly half the time", live.score_display(0.40, self.disp)["tooltip"])
        self.assertNotIn("roughly half", live.score_display(0.10, self.disp)["tooltip"])


class RewordLiveTests(unittest.TestCase):
    def old_live(self) -> dict:
        return {"score": {"display": {"6": {"text": "More likely than not", "words": True,
                                            "tooltip": "about 76% in testing terms"},
                                      "3": {"text": "5%", "words": False, "tooltip": "4.9%"}},
                          "previous": {"display": {"text": "Elevated", "words": True, "tooltip": "about 40% in testing terms"}},
                          "compare_label": "vs. last week's backtest score"},
                "triggers": {"rule": "Red if trigger 1, 2 or 4 is red; amber if one of 1, 2, 4 is amber or red and "
                                     "another panel trigger is amber or red; otherwise green."}}

    def test_old_file_gets_new_words(self):
        lv = self.old_live()
        common.reword_live(lv)
        d6 = lv["score"]["display"]["6"]
        self.assertEqual(d6["text"], "High")
        self.assertEqual(d6["tooltip"], "about 76% in testing terms. " + common.WORDS_NOTE)
        self.assertEqual(lv["score"]["display"]["3"]["tooltip"], "4.9%")          # numbers below 35%: unchanged
        self.assertIn(common.WORDS_NOTE, lv["score"]["previous"]["display"]["tooltip"])
        self.assertEqual(lv["score"]["compare_label"], "vs. last week's tested-on-history score")
        self.assertIn("another trigger that counts toward the status", lv["triggers"]["rule"])
        self.assertNotIn("panel", lv["triggers"]["rule"])

    def test_twice_is_same_as_once(self):
        once = self.old_live()
        common.reword_live(once)
        twice = json.loads(json.dumps(once))
        common.reword_live(twice)
        self.assertEqual(once, twice)

    def test_same_sentence_in_both_places(self):
        self.assertEqual(live.WORDS_NOTE, common.WORDS_NOTE)


if __name__ == "__main__":
    unittest.main()
