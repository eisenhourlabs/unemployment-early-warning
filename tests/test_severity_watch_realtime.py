"""Review WP8 test T2: the fixed rule of the real-time Duration watch check (src/model/severity_watch_realtime.py)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "model"))
import severity_watch_realtime as swr  # noqa: E402


def rows(lt, med):
    """shares()-style rows from four shares per outcome (falling, green, amber, red)."""
    out = []
    for outcome, s in (("lt_share_up", lt), ("median_up", med)):
        for band, v in zip(["falling", "green", "amber", "red"], s):
            out.append({"outcome": outcome, "band": band, "months": 0 if v is None else 10, "share_followed": v})
    return out


class RuleTest(unittest.TestCase):
    def test_passes(self):
        self.assertEqual(swr.rule_ok(rows([0.01, 0.17, 0.58, 0.83], [0.02, 0.10, 0.51, 0.57])),
                         {"lt_share_up": True, "median_up": True})

    def test_each_condition(self):
        self.assertFalse(swr.rule_ok(rows([0.01, 0.17, 0.58, 0.49], [0.02, 0.1, 0.5, 0.6]))["lt_share_up"])   # red < 0.5
        self.assertFalse(swr.rule_ok(rows([0.11, 0.17, 0.58, 0.83], [0.02, 0.1, 0.5, 0.6]))["lt_share_up"])   # falling > 0.1
        self.assertFalse(swr.rule_ok(rows([0.01, 0.60, 0.58, 0.83], [0.02, 0.1, 0.5, 0.6]))["lt_share_up"])   # no rise
        self.assertFalse(swr.rule_ok(rows([0.01, 0.17, 0.58, 0.83], [0.02, 0.1, None, 0.6]))["median_up"])   # empty band

    def test_realtime_value_uses_the_lag(self):
        # a month's real-time value can only use weeks published by the month end (12-day lag)
        import pandas as pd
        from realtime import as_known_on
        d = pd.Timestamp("2008-12-31")
        self.assertLessEqual(as_known_on("CCSA", d).index.max() + pd.Timedelta(days=12), d)


if __name__ == "__main__":
    unittest.main()
