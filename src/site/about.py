"""
About page: what the site is, definitions, sources (from the catalog), update schedule, revisions,
method notes and the disclaimer. Called by build_site.py.
"""

import csv
import json
import re
import sys

import pandas as pd

from common import ROOT, claims_weekly
from states import WEIGHTED_SENTENCE

LICENCE_TEXT = {
    "public": "Public",
    "citation-required": "Copyright; charted with the required citation, not offered for download",
    "check-terms": "Terms of use not yet confirmed; not shown or offered for download",
    "restricted": "Licence does not allow republishing; not used",
    "reference-only": "Public; shown as a reference marker (with its release date) and not offered for download",
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
        elif r["fetcher"] == "local-only":   # Chicago Fed LMI: listed, never shown (licence)
            link, via = CHICAGO_LMI_LINK, ""
        else:
            link, via = DOL_LINK, ""
        name = r["name"] + (" (by state)" if sid.startswith("STATE_") else "")
        out.append({"name": name, "id": "" if sid.startswith(("STATE_", "DOL_", "CHI_")) else sid,
                    "publisher": r["source"] + via, "frequency": r["frequency"],
                    "licence": LICENCE_TEXT.get(r["license"], r["license"]), "link": link,
                    "page": r["dashboard_page"]})
    return out


def iur_check() -> tuple[float, int]:
    """Largest difference between our SA continuing claims rate and DOL's published IUR, and the first year."""
    c = claims_weekly().dropna(subset=["cc_rate_sa", "iur_sa_published"])
    return (c.cc_rate_sa - c.iur_sa_published).abs().max(), int(c.week_ended.dt.year.min())


def fallback_accuracy() -> dict | None:
    """Tested error of the shutdown fallback (stage 4c Monte Carlo, the method in use), for the method note."""
    path = ROOT / "data" / "model" / "fallback_validation_mc.csv"
    if not path.exists():
        return None
    sys.path.insert(0, str(ROOT / "src" / "fetchers"))
    import dol_state_fallback as fb
    mc = pd.read_csv(path)
    col = f"err_{fb.FILL_METHOD}"
    out = {"first_year": int(str(mc.week.min())[:4])}
    for m in ("ic", "cc"):
        e = mc[mc.measure == m][col].abs()
        out[m] = {"median": f"{e.median():.1f}", "p90": f"{e.quantile(0.9):.1f}"}
    return out


def model_card() -> dict | None:
    """The "Model card" section (review X5): the model in use and its key tested numbers, read from the same files
    as docs/model_card.md (which tests/test_model_card.py keeps in step). None if a file is missing: no section."""
    model = ROOT / "data" / "model"
    try:
        frozen = json.loads(sorted((model / "frozen").glob("model_*.json"))[-1].read_text())
        s = pd.read_csv(model / "score_skill_summary.csv").set_index("basis")
        fe = pd.read_csv(model / "forecast_evaluation.csv")
        reg = pd.read_csv(model / "forecast_evaluation_regimes.csv")
    except (OSError, IndexError):
        return None
    pc = lambda v: f"{v * 100:.0f}%"
    sg = lambda v: f"{v:+.2f}".replace("-", "−")
    rows = []
    for colour, label in (("red", "Red (50% and above)"), ("amber", "Amber (20% to 50%)"),
                          ("green", "Green (under 20%)")):
        rows.append({"label": label, "cells": [f"{int(s.loc[b, 'n_' + colour])} months, "
                                               f"{pc(s.loc[b, 'hit_' + colour])} followed by an event"
                                               for b in ("first_published", "revised")]})
    rows.append({"label": "Skill against the long-run average (90% range)",
                 "cells": [f"{sg(s.loc[b, 'skill'])} ({sg(s.loc[b, 'skill_p05'])} to {sg(s.loc[b, 'skill_p95'])})"
                           for b in ("first_published", "revised")]})
    ur = fe[(fe.target == "ur") & (fe.subset == "2000-on excl. 2020")].set_index("horizon")
    during = reg[(reg.target == "ur") & (reg.regime == "during an event")].set_index("horizon")
    hs = [3, 6, 12]
    rv = s.loc["revised"]
    return {"year": frozen["model_year"], "frozen": pd.Timestamp(frozen["frozen_at"][:10]).strftime("%B %d, %Y")
            .replace(" 0", " "), "known_by": pd.Timestamp(frozen["data_known_by"]).strftime("%B %d, %Y").replace(" 0", " "),
            "next_refit": f"January {frozen['model_year'] + 1}", "months": int(rv.months),
            "events": int(rv.events_in_test), "rows": rows,
            "cover_all": " / ".join(pc(ur.loc[h].cover80) for h in hs),
            "cover_during": " / ".join(pc(during.loc[h].cover80) for h in hs)}


def build() -> dict:
    max_diff, since = iur_check()
    return {"sources": source_rows(), "iur_max_diff": f"{max_diff:.2f}", "iur_since": since,
            "weighted_sentence": WEIGHTED_SENTENCE, "fallback": fallback_accuracy(), "card": model_card()}
