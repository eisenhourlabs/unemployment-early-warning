"""
Tests for the States page data (Phase 4 stage 4b). Run them with:
    python -m unittest discover -s tests -v

What they check:
  1. rounded(): blanks become None, whole numbers stay whole, decimals are rounded.
  2. The page's data file (site/assets/states.json, built by src/site/states.py) on the real data:
     every per-state array lines up with the list of weeks / months; the weighted figures are there but
     no weights, ranks or the word "footprint" are (decision O1).
  3. The Data & Downloads page never offers the weighted files.
Test 2 needs data/processed/states/ (made by src/transforms/state_measures.py); it is skipped where that is missing.
"""

import json
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "site"))
import states  # noqa: E402

STATES_DIR = ROOT / "data" / "processed" / "states"


class TestRounded(unittest.TestCase):
    def test_blanks_whole_and_decimals(self):
        self.assertEqual(states.rounded([1.26, None, float("nan"), 2.0], 1), [1.3, None, None, 2.0])
        out = states.rounded([1234.6, 3.0], 0)
        self.assertEqual(out, [1235, 3])
        self.assertTrue(all(isinstance(v, int) for v in out))


@unittest.skipUnless((STATES_DIR / "state_weekly.csv").exists(), "state measures not built on this machine")
class TestPayload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = states.states_payload()

    def test_arrays_line_up(self):
        p = self.p
        n_areas, n_weeks, n_months = len(p["areas"]), len(p["weeks"]), len(p["months"])
        self.assertEqual(n_areas, 53)
        self.assertEqual(sum(a["map"] for a in p["areas"]), 51)          # 50 states + DC on the map
        for key, arrays in p["w"].items():
            self.assertEqual(len(arrays), n_areas, key)
            self.assertTrue(all(len(a) == n_weeks for a in arrays), key)
        for key, arrays in p["m"].items():
            self.assertTrue(all(len(a) == n_months for a in arrays), key)
        for key, values in p["t"].items():
            self.assertEqual(len(values), n_weeks, key)
        self.assertEqual(p["weeks"], sorted(p["weeks"]))

    def test_values_match_source(self):
        """Texas, latest week with a year-on-year change: the payload holds the source value, rounded."""
        p = self.p
        sw = pd.read_csv(STATES_DIR / "state_weekly.csv").dropna(subset=["ic_yoy_pct"])
        last = sw[sw.state == "TX"].iloc[-1]
        a = [x["code"] for x in p["areas"]].index("TX")
        i = p["weeks"].index(last.week_ended)
        self.assertEqual(p["w"]["icy"][a][i], round(last.ic_yoy_pct, 1))
        self.assertEqual(p["w"]["ic4"][a][i], int(round(last.initial_claims_4wk)))

    def test_no_weights_in_payload(self):
        text = json.dumps(self.p)
        self.assertNotIn("footprint", text.lower())
        self.assertNotIn("rank", text.lower())
        w = pd.read_csv(ROOT / "config" / "state_weights.csv", comment="#")
        for v in w.weight:
            self.assertNotIn(f"{v:.6f}", text)


class TestDownloads(unittest.TestCase):
    def test_weighted_files_never_offered(self):
        sys.path.insert(0, str(ROOT / "src" / "site"))
        import downloads
        stems = [s for s, _, _ in downloads.STATE_FILES]
        self.assertEqual(stems, ["state_weekly", "state_monthly", "diffusion_weekly"])
        self.assertFalse(any(s.startswith("weighted") for s in stems))


if __name__ == "__main__":
    unittest.main()
