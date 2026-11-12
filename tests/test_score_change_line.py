"""
Tests for the line under the Overview score and the score sentence (review WP9 C2, 2026-11). Run them with:
    python -m unittest discover -s tests -v

What they check:
  1. A first live run says exactly "First live run": no arrow, no number, even when the tested-on-history
     point it follows differs (change_pt = -0.6).
  2. When the score is shown as a whole percent, a move under 0.5 point reads "unchanged" (the display
     rounds to whole percent, so it cannot be seen); 0.5 point or more shows the arrow and the size.
  3. When the score is shown in words (verbal bands), moves of 0.05 point or more are still shown.
  4. The "What changed" sentence for a first live run: "The early-warning score is 2%, green, in its first
     live run."
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "site"))
import overview  # noqa: E402


def score(change_pt, first=False, words=False, text="2%", label="vs. last week"):
    """A minimal live_latest.json 'score' block with only the fields the two functions read."""
    return {"change_pt": change_pt, "first_live_run": first, "compare_label": label, "colour": "green",
            "display": {"6": {"text": text, "words": words}},
            "previous": {"display": {"text": "2%"}}}


class ChangeLine(unittest.TestCase):
    def test_first_live_run(self):
        self.assertEqual(overview.change_line(score(-0.6, first=True)), "First live run")

    def test_small_move_unchanged_when_shown_as_number(self):
        self.assertEqual(overview.change_line(score(0.42, label="vs. the run of Nov 8")),
                         "unchanged vs. the run of Nov 8")
        self.assertEqual(overview.change_line(score(-0.49)), "unchanged vs. last week")

    def test_move_of_half_a_point_is_shown(self):
        self.assertEqual(overview.change_line(score(0.5)), "▲ 0.5 pt vs. last week")
        self.assertEqual(overview.change_line(score(-1.26)), "▼ 1.3 pt vs. last week")

    def test_words_keep_the_fine_threshold(self):
        self.assertEqual(overview.change_line(score(0.3, words=True, text="Elevated")), "▲ 0.3 pt vs. last week")
        self.assertEqual(overview.change_line(score(0.01, words=True, text="Elevated")), "unchanged vs. last week")


class ScoreSentence(unittest.TestCase):
    def test_first_live_run_sentence(self):
        live = {"score": score(-0.6, first=True)}
        self.assertEqual(overview.score_sentence(live),
                         "The early-warning score is 2%, green, in its first live run.")


if __name__ == "__main__":
    unittest.main()
