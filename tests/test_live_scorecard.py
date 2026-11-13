"""
Tests for the live scorecard (review WP4 Part C, src/model/live_scorecard.py). Run with:
    python -m unittest discover -s tests -v

Three made-up archive files and a made-up leg history (an event starts in 2021-03):
  - a green run in 2020-06, old: outcome known, no start within 6 months  -> False
  - a red run in 2020-12, old: an event starts in 2021-03                  -> True
  - a recent run in 2022-01 (history ends 2022-03): outcome not known      -> blank
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "model"))
import live_scorecard as ls  # noqa: E402


def write(folder: Path, asof: str, p6: float, colour: str) -> None:
    (folder / asof[:4]).mkdir(exist_ok=True)
    d = {"asof": asof, "inputs": {"initial_claims_week": asof}, "score": {"p6": p6, "colour": colour}}
    (folder / asof[:4] / f"{asof}_ic{asof}_ur{asof[:7]}.json").write_text(json.dumps(d), encoding="utf-8")


class Scorecard(unittest.TestCase):
    def test_three_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            write(folder, "2020-06-10", 0.02, "green")
            write(folder, "2020-12-10", 0.60, "red")
            write(folder, "2022-01-10", 0.05, "green")
            idx = pd.date_range("2019-01-01", "2022-03-01", freq="MS")
            legs = pd.DataFrame({"ur": False, "claims": idx.isin([pd.Timestamp("2021-03-01")])}, index=idx)
            card = ls.scorecard(ls.read_runs(folder), legs).set_index("asof")
        self.assertEqual(list(card.outcome_known), [True, True, False])
        self.assertEqual(card.loc["2020-06-10", "event_started_within_6m"], False)
        self.assertEqual(card.loc["2020-12-10", "event_started_within_6m"], True)
        self.assertTrue(pd.isna(card.loc["2022-01-10", "event_started_within_6m"]))
        self.assertFalse(card.during_event.any())


if __name__ == "__main__":
    unittest.main()
