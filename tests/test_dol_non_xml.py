"""
DOL sometimes answers the national claims request with something that is not the XML report, while still reporting
success. dol_national.py should try again, and if it never gets XML, say how the reply began and keep the stored
data. Uses made-up replies and no network.
Run: python -m unittest discover -s tests -v
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "fetchers"))
import dol_national  # noqa: E402

GOOD = b"<r539><week><weekEnded>01/03/2026</weekEnded></week></r539>"
PLAIN_TEXT = b"Service temporarily unavailable.\r\nPlease try again later."
WEB_PAGE = b"<html><body><p>Down for maintenance</p></body></html>"   # well-formed, but not the report


class NonXmlReply(unittest.TestCase):
    def run_with(self, replies, function):
        """Run `function` with DOL's replies faked. Returns (result or error, number of requests, waits)."""
        with mock.patch.object(dol_national, "download", side_effect=replies) as download, \
                mock.patch.object(dol_national.time, "sleep") as sleep, \
                contextlib.redirect_stdout(io.StringIO()):
            try:
                result = function()
            except Exception as e:
                result = e
        return result, download.call_count, [c.args[0] for c in sleep.call_args_list]

    def get(self, replies):
        return self.run_with(replies, lambda: dol_national.download_xml({}))

    def test_good_reply_is_used_at_once(self):
        root, requests_made, waits = self.get([GOOD])
        self.assertEqual(root.find("week/weekEnded").text, "01/03/2026")
        self.assertEqual((requests_made, waits), (1, []))

    def test_tries_again_after_bad_replies(self):
        for bad in (PLAIN_TEXT, WEB_PAGE, b""):
            root, requests_made, waits = self.get([bad, GOOD])
            self.assertEqual(root.tag, "r539", bad)
            self.assertEqual((requests_made, waits), (2, [60]), bad)

    def test_gives_up_after_three_and_shows_how_the_reply_began(self):
        error, requests_made, waits = self.get([PLAIN_TEXT] * 3)
        self.assertEqual((requests_made, waits), (3, [60, 120]))
        self.assertIn("not the XML report", str(error))
        self.assertIn("Service temporarily unavailable. Please try again later.", str(error))
        self.assertIn(f"{len(PLAIN_TEXT)} bytes", str(error))

    def test_shown_text_is_one_short_line(self):
        error, _, _ = self.get([b"line one\n\t\x00line two " + b"x" * 5000] * 3)
        self.assertNotRegex(str(error), r"[\x00-\x1f]")
        self.assertLess(len(str(error)), 350)

    def test_failure_is_logged_and_nothing_is_saved(self):
        with mock.patch.object(dol_national, "log_fetch") as log_fetch, \
                mock.patch.object(dol_national, "save_latest") as save_latest, \
                mock.patch.object(dol_national, "update_metadata") as update_metadata:
            code, _, _ = self.run_with([PLAIN_TEXT] * 3, dol_national.main)
        self.assertEqual(code, 1)
        self.assertTrue(log_fetch.call_args.args[1].startswith("FAILED: "))
        self.assertIn("Service temporarily unavailable", log_fetch.call_args.args[1])
        save_latest.assert_not_called()
        update_metadata.assert_not_called()


if __name__ == "__main__":
    unittest.main()
