"""
Check the shutdown-fallback labels in the BUILT site (no browser needed, so it also runs in the cloud).

  --expect estimates   during a (simulated) delay: freshness line "estimated from state filings", the score note
                       "Provisional", estimate legends on the claims charts (Overview, Job Losses, Duration), and
                       data/model/live_latest.json flagged provisional
  --expect none        normal / after the official week arrives: none of those anywhere, live run not provisional

Used by the "Simulate delay" workflow (Phase 4 review, Gate 1) and on the PC.
Run:  python src/checks/check_estimate_labels.py --expect estimates|none      (exit code 1 if a check fails)
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
LIVE = ROOT / "data" / "model" / "live_latest.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect", choices=["estimates", "none"], required=True)
    want = ap.parse_args().expect == "estimates"
    pages = {n: (SITE / n).read_text(encoding="utf-8") for n in ("index.html", "job-losses.html", "duration.html")}
    provisional = json.loads(LIVE.read_text(encoding="utf-8")).get("provisional", False)
    checks = [
        ("freshness line says 'estimated from state filings'", "estimated from state filings" in pages["index.html"]),
        ("score note says 'Provisional'", "Provisional: the score and forecasts use claims estimated" in pages["index.html"]),
        ("Overview claims charts carry an estimate legend", "estimate (release delayed)" in pages["index.html"].lower()),
        ("Job Losses charts carry an estimate legend", "estimate (release delayed)" in pages["job-losses.html"].lower()),
        ("Duration charts carry an estimate legend", "estimate (release delayed)" in pages["duration.html"].lower()),
        ("live run flagged provisional", provisional is True),
    ]
    failed = 0
    print(f"Estimate labels, expecting {'ESTIMATES' if want else 'NONE'}:")
    for name, present in checks:
        ok = present == want
        failed += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {'present' if present else 'absent'}")
    print("ALL PASS" if not failed else f"{failed} FAILED")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
