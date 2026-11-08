"""
Tests for the live run's permanent archive (stage 3e-3). Run them with:
    python -m unittest discover -s tests -v
The "Refresh data" workflow runs them before the model step.

What they check:
  1. write_archive creates a new file, and REFUSES to overwrite an existing one (FileExistsError), leaving the
     original untouched: the workflow fails rather than overwrite a past result.
  2. The model step runs only when there is a new claims week or a new unemployment month since the last archived
     run, and finds the newest archived run correctly.
  3. archive_name puts the run date and its inputs in the file name.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "model"))
import live  # noqa: E402

INPUTS = {"initial_claims_week": "2026-10-31", "continuing_claims_week": "2026-10-24",
          "unemployment_month": "2026-10-01", "unemployment_rate": 4.1}


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_then_refuse_overwrite(self):
        name = live.archive_name(pd.Timestamp("2026-11-12"), INPUTS)
        path = live.write_archive(self.dir, name, {"inputs": INPUTS, "score": {"p6": 0.02}})
        self.assertTrue(path.exists())
        with self.assertRaises(FileExistsError):
            live.write_archive(self.dir, name, {"inputs": INPUTS, "score": {"p6": 0.99}})
        # the original file is unchanged
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["score"]["p6"], 0.02)

    def test_name_has_date_and_inputs(self):
        self.assertEqual(live.archive_name(pd.Timestamp("2026-11-12"), INPUTS),
                         "2026/2026-11-12_ic2026-10-31_ur2026-10.json")

    def test_new_inputs_rule(self):
        self.assertEqual(live.latest_archived_inputs(self.dir), (None, None, None))
        self.assertTrue(live.has_new_inputs(INPUTS, (None, None, None)))           # nothing archived yet: run
        live.write_archive(self.dir, live.archive_name(pd.Timestamp("2026-11-08"), INPUTS), {"inputs": INPUTS})
        last = live.latest_archived_inputs(self.dir)
        self.assertEqual(last[1:], ("2026-10-31", "2026-10-01"))
        self.assertFalse(live.has_new_inputs(INPUTS, last))                        # same inputs: skip
        self.assertTrue(live.has_new_inputs({**INPUTS, "initial_claims_week": "2026-11-07"}, last))   # new claims week
        self.assertTrue(live.has_new_inputs({**INPUTS, "unemployment_month": "2026-11-01"}, last))    # new jobs report
        later = {**INPUTS, "initial_claims_week": "2026-11-07"}
        live.write_archive(self.dir, live.archive_name(pd.Timestamp("2026-11-12"), later), {"inputs": later})
        self.assertEqual(live.latest_archived_inputs(self.dir)[1], "2026-11-07")  # newest file wins


if __name__ == "__main__":
    unittest.main()
