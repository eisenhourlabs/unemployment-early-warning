"""Review WP8 test T1: the chance of a large rise (src/model/tail_prob.py) and its fixed display rule."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "model"))
import tail_prob as tp  # noqa: E402


class TailProbTest(unittest.TestCase):
    def test_spec_cases(self):
        # The specification's unit test: all draws y0 + 1 -> 1.0; all draws y0 -> 0.0
        y0 = 4.4
        self.assertEqual(tp.p_rise_050(np.full(100, y0 + 1), y0), 1.0)
        self.assertEqual(tp.p_rise_050(np.full(100, y0), y0), 0.0)

    def test_exact_half_point_counts(self):
        # 4.1 -> 4.6 is a rise of exactly 0.5 on the published one-decimal rate
        self.assertTrue(tp.met("ur", 4.1, [4.6])[0])
        self.assertFalse(tp.met("ur", 4.1, [4.5])[0])

    def test_claims_twenty_percent(self):
        self.assertEqual(tp.p_rise_20pct([1.2, 1.3, 1.0, 1.1], 1.0), 0.5)
        self.assertIsNone(tp.p_rise("ic", [1.0], 1.0))

    def test_bins(self):
        self.assertEqual([tp.bin_label(p) for p in (0.0, 0.0999, 0.10, 0.2499, 0.25, 0.4999, 0.5, 1.0)],
                         ["0-10%", "0-10%", "10-25%", "10-25%", "25-50%", "25-50%", "50-100%", "50-100%"])

    def test_rule(self):
        row = lambda n, s, o: {"origins": n, "mean_stated": s, "observed": o}
        good = [row(200, 0.03, 0.02), row(40, 0.17, 0.20), row(10, 0.35, 0.60), row(15, 0.7, 0.9)]
        self.assertTrue(tp.rule(good)["show"])
        # (a) fails if any step does not rise
        self.assertFalse(tp.rule([row(200, 0.03, 0.02), row(40, 0.17, 0.20), row(10, 0.35, 0.15)])["monotone"])
        # (b) fails if a bin with 20+ origins is off by more than 0.15; small bins are exempt
        self.assertFalse(tp.rule([row(200, 0.03, 0.02), row(40, 0.17, 0.40)])["calibrated"])
        self.assertTrue(tp.rule([row(200, 0.03, 0.02), row(19, 0.17, 0.40)])["calibrated"])
        # empty bins are skipped; a single non-empty bin cannot show a rise
        self.assertTrue(tp.rule([row(200, 0.03, 0.02), row(0, np.nan, np.nan), row(30, 0.3, 0.35)])["show"])
        self.assertFalse(tp.rule([row(200, 0.03, 0.02)])["show"])


if __name__ == "__main__":
    unittest.main()
