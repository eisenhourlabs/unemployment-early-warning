"""
About page: what the site is, definitions, sources (from the catalog), update schedule, revisions,
method notes and the disclaimer. Called by build_site.py.
"""

import csv
import re

import pandas as pd

from common import ROOT, claims_weekly

LICENCE_TEXT = {
    "public": "Public",
    "citation-required": "Copyright; charted with the required citation, not offered for download",
    "check-terms": "Terms of use not yet confirmed; not shown or offered for download",
    "restricted": "Licence does not allow republishing; not used",
}
DOL_LINK = "https://oui.doleta.gov/unemploy/claims.asp"
CHICAGO_LMI_LINK = "https://www.chicagofed.org/research/data/chicago-fed-labor-market-indicators/index"


def source_rows() -> list[dict]:
    """One row per active catalog series (adding a catalog row adds a row here)."""
    with open(ROOT / "config" / "series_catalog.csv", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["status"] == "active"]
    out = []
    for r in rows:
        sid = r["series_id"]
        if r["fetcher"] == "fred":
            example = re.search(r"e\.g\. ([A-Z0-9]+)", r["name"])     # state rows: "(e.g. TXICLAIMS)"
            link = f"https://fred.stlouisfed.org/series/{example.group(1) if example else sid}"
            via = "" if "FRED" in r["source"] else " via FRED"
        elif r["fetcher"] == "chicagofed_json":
            link, via = CHICAGO_LMI_LINK, ""
        else:
            link, via = DOL_LINK, ""
        name = r["name"] + (" (44 footprint states)" if sid.startswith("STATE_") else "")
        out.append({"name": name, "id": "" if sid.startswith(("STATE_", "DOL_", "CHI_")) else sid,
                    "publisher": r["source"] + via, "frequency": r["frequency"],
                    "licence": LICENCE_TEXT.get(r["license"], r["license"]), "link": link,
                    "page": r["dashboard_page"]})
    return out


def iur_check() -> tuple[float, int]:
    """Largest difference between our SA continuing claims rate and DOL's published IUR, and the first year."""
    c = claims_weekly().dropna(subset=["cc_rate_sa", "iur_sa_published"])
    return (c.cc_rate_sa - c.iur_sa_published).abs().max(), int(c.week_ended.dt.year.min())


def build() -> dict:
    max_diff, since = iur_check()
    return {"sources": source_rows(), "iur_max_diff": f"{max_diff:.2f}", "iur_since": since,
            "issues_url": "https://github.com/eisenhourlabs/unemployment-early-warning/issues/new"}
