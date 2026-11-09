"""
Phase 4 review, Gate 1: the nowcast uses the reference week's claims as soon as they are on file in a run dated today
(Thanksgiving: DOL publishes on Wednesday), and keeps the fixed lag for runs dated in the past.
Run with:  python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "model"))
import live  # noqa: E402

REF = pd.Timestamp("2026-11-14")            # November reference week (contains the 12th)
WED = pd.Timestamp("2026-11-25")            # Thanksgiving-week release day (11 days after the week ends)


class TestClaimsAvailable(unittest.TestCase):
    def setUp(self):
        self.w = pd.DataFrame({"CCSA": [1_900_000.0]}, index=[REF])

    def test_thanksgiving_live_run_uses_data_on_file(self):
        # live run on Wednesday Nov 25: 11 days after the week, below the 12-day lag, but the figure is out
        self.assertTrue(live.claims_available(self.w, "CCSA", REF, 12, WED, today=WED))

    def test_past_date_keeps_the_lag(self):
        # re-running Nov 25 later (today = Dec 10): the fixed lag still applies, so not yet available on Nov 25
        self.assertFalse(live.claims_available(self.w, "CCSA", REF, 12, WED, today=pd.Timestamp("2026-12-10")))
        self.assertTrue(live.claims_available(self.w, "CCSA", REF, 12, pd.Timestamp("2026-11-26"),
                                              today=pd.Timestamp("2026-12-10")))

    def test_missing_week_is_never_available(self):
        self.assertFalse(live.claims_available(self.w, "CCSA", pd.Timestamp("2026-11-21"), 12, WED, today=WED))


if __name__ == "__main__":
    unittest.main()
