"""
The FRED API key must never appear in an error message from fred_get: callers write that text to data/fetch_log.csv,
which the refresh workflow commits. Uses a made-up key and no network.
Run: python -m unittest discover -s tests -v
"""

import sys
import traceback
import unittest
from pathlib import Path
from unittest import mock

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "fetchers"))
import fred_fetcher  # noqa: E402

FAKE_KEY = "notarealkey0123456789abcdef01234"


def connection_error(key_in_url):
    """The kind of message requests produces when it cannot connect: it includes the address and its parameters."""
    return requests.ConnectionError(
        "HTTPSConnectionPool(host='api.stlouisfed.org', port=443): Max retries exceeded with url: "
        f"/fred/series?series_id=UNRATE&api_key={key_in_url}&file_type=json (Caused by NewConnectionError)")


class FredKeyRedaction(unittest.TestCase):
    def error_from(self, key=FAKE_KEY, **get_behaviour):
        """Call fred_get with requests.get faked, and return the exception it raises."""
        with mock.patch.object(fred_fetcher.requests, "get", **get_behaviour), \
                mock.patch.object(fred_fetcher.time, "sleep"):
            try:
                fred_fetcher.fred_get("series", {"series_id": "UNRATE"}, key)
            except Exception as e:
                return e
        self.fail("fred_get did not raise")

    def assert_clean(self, error, secret):
        self.assertNotIn(secret, str(error))
        self.assertNotIn(secret, "".join(traceback.format_exception(error)))   # includes any chained error

    def test_connection_error_hides_key(self):
        error = self.error_from(side_effect=connection_error(FAKE_KEY))
        self.assert_clean(error, FAKE_KEY)
        # still useful for finding out what went wrong
        self.assertIn("ConnectionError", str(error))
        self.assertIn("series_id=UNRATE", str(error))

    def test_badly_typed_key_is_hidden_when_encoded_in_the_address(self):
        # e.g. quotation marks left around the key in config/.env: the address shows them as %22
        error = self.error_from(key=f'"{FAKE_KEY}"', side_effect=connection_error(f"%22{FAKE_KEY}%22"))
        self.assert_clean(error, FAKE_KEY)

    def test_rejected_request_that_echoes_the_key(self):
        response = mock.Mock(status_code=400, text="")
        response.json.return_value = {"error_message": f"Bad Request. api_key {FAKE_KEY} is not registered."}
        error = self.error_from(return_value=response)
        self.assert_clean(error, FAKE_KEY)
        self.assertIn("Bad Request", str(error))


if __name__ == "__main__":
    unittest.main()
