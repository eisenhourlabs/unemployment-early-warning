# CLAUDE.md — Unemployment Early-Warning Dashboard

Read this first in every session. It is published in a PUBLIC repository, so it must never name an
employer, contain company data, or hold secrets. Private context lives in `internal/` (git-ignored):
read `internal/README.md` and `internal/project_instructions.md` at the start of a session if they exist.

## What we're building
An automated dashboard showing where US unemployment has been, where it is now versus history, and a
forecast range (3–6 months is the priority; 12 months shown too) with a green / amber / red layoff-risk
signal. Built to inform consumer-lending and credit involuntary-unemployment (IUI) insurance decisions,
so always cover BOTH dimensions:
- new job losses (drives claim frequency): initial claims, WARN notices, layoffs rates
- duration of unemployment (drives claim severity): continuing claims, weeks unemployed, job-finding rate
Secondary purpose: viewers can download any public series as CSV/XLSX.

## The person you're working with
Troy is the owner and maintainer. He is an actuary (comfortable with statistics, regressions,
uncertainty) but NEW to Python, Git, GitHub and VS Code. So:
- Explain what you're about to do in plain words before running commands, and why.
- Prefer small, readable scripts with comments over clever code. One script per step.
- When something needs Troy to act (sign in, approve, click in a browser), give exact steps.
- Teach as you go: after a new concept (virtual environment, commit, push, secret), add one sentence on what it is.
- Use precise statistical language for the modeling work and always show assumptions and uncertainty.

## Environment
- Windows PC, VS Code with the Claude Code extension, PowerShell terminal.
- Python virtual environment in `.venv` (create it if missing: `python -m venv .venv`,
  activate with `.venv\Scripts\Activate.ps1`, then `pip install -r requirements.txt`).
- Secrets live in `config/.env` (git-ignored) locally and as GitHub repository secrets in the cloud.
  Never print, commit, or paste the FRED API key anywhere.

## Hard rules
- Public data only on the site; free sources only. NOT allowed: Indeed, ISM, Conference Board.
  Challenger: headline only, with attribution, not downloadable.
- No employer name, logo or branding anywhere in committed files or on the site. State weights are
  called "footprint weights". Anything company-specific goes in `internal/`.
- Consumer credit stress (Tier 5) and any company data are deferred to a future phase. Don't build them.
- Alerts exist but stay OFF (`ALERTS_ENABLED=false`) unless Troy says otherwise.
- Add indicators by adding rows to `config/series_catalog.csv`, not by hard-coding series in scripts.
- Keep data vintages (`data/vintages/`); backtests must use data as it was known at the time.
  EXCEPTION: DOL data (`data/processed/dol/`) keeps only the latest figures, with no vintages. Each run
  overwrites revised history and logs the revision in `docs/data_revisions.md`. For real-time backtests of
  national claims, use the FRED vintages of ICSA/CCSA/ICNSA/CCNSA instead.
- DOL data starts in 1995 (all DOL files).
- Thresholds and model weights come from backtests (2001, 2008, 2020 and recent data). Record every
  decision and its reason in `docs/decisions.md`.
- Verify current release dates and series status before stating them; data and schedules change.
- Ask before anything hard to undo: deleting files, rewriting Git history, changing repository settings.

## Layout
| Path | Purpose |
| --- | --- |
| `config/series_catalog.csv` | Every series: source, fetcher, frequency, tier, role, page, status (active/future) |
| `config/state_weights.csv` | Footprint ranking by state (44 states, rank only; exact weights in `internal/`) |
| `config/dol_columns.csv` | DOL coded column names -> plain names, with how each was confirmed (verified / label / inferred / unclear) |
| `src/fetchers/fred_fetcher.py` | Downloads all active FRED series (incl. per-state series) to `data/processed/` |
| `src/fetchers/dol_*.py` | DOL pipeline: `dol_national.py` (ETA 539), `dol_state.py` (ar539/ar5159/ar218), `dol_recent_weeks.py` (merged table + preliminary weeks), `dol_common.py` (shared) |
| `src/fetchers/wait_for_claims.py` | Thursday run: waits up to 60 min for the claims release on FRED; never fails |
| `src/transforms/dol_rates.py` | Claims rates, 12-month exhaustion rate, average duration |
| `src/checks/dol_checks.py` | DOL vs FRED (fails run above 1%); SA continuing claims rate vs DOL IUR (report only) |
| `data/processed/dol/` | DOL outputs (latest figures only) |
| `docs/data_revisions.md` | Automatic log of DOL revisions |
| `docs/dashboard_requirements.md` | What the Phase 2 dashboard must show |
| `src/alerts/alerts.py` | Optional alerts (off) |
| `src/signals/`, `src/forecast/` | Phase 3: triggers, composite score, forecast fan |
| `site/` | Phase 2: the dashboard pages |
| `.github/workflows/refresh-data.yml` | Scheduled cloud refresh (weekday mornings + Thursday after claims) |
| `docs/decisions.md` | Decision log — keep it current |
| `docs/getting_started.md` | Manual setup steps (fallback) |
| `internal/` | Private notes, never committed |

## Useful commands
- Fetch a few series: `python src\fetchers\fred_fetcher.py UNRATE ICSA CCSA`
- Fetch everything (~160 series, ~2 min): `python src\fetchers\fred_fetcher.py`
- Test alerts (prints only while off): `python src\alerts\alerts.py`
- DOL pipeline, in order (run the FRED fetch first):
  `python src\fetchers\dol_national.py`, `python src\fetchers\dol_state.py`,
  `python src\fetchers\dol_recent_weeks.py`, `python src\transforms\dol_rates.py`, `python src\checks\dol_checks.py`

## Status (2026-11-07)
- Phase 0 done: folders, catalog (35 active rows), footprint weights, FRED fetcher (tested only against
  mocked API responses), scheduled workflow, alerts module.
- 2026-11-07: `.venv` created; first live full fetch done, all 159 active series OK after one catalog ID fix
  (Empire State, logged in docs/decisions.md).
- 2026-11-07: Git initialized; pushed to public repo github.com/eisenhourlabs/unemployment-early-warning;
  FRED_API_KEY repository secret set.
- 2026-11-07: first "Refresh data" workflow run green (run 42398782692): 159 ok, 0 failed, ~5 min; data-bot commit pushed.
- 2026-11-07: open items from that run fixed (see docs/decisions.md), confirmed green in run 42403686070:
  fetcher now fails the run if any Tier 1 series fails or >10% of series fail, and prints a failed-series
  summary; workflow uses actions/checkout@v7, actions/setup-python@v7 and Python 3.15 (matches .venv).
- Watch: GitHub is moving ubuntu-latest to Ubuntu 26 (Python 3.15 is available there too).
- 2026-11-07: DOL pipeline built and tested locally (ETA 539 national, ar539/ar5159/ar218, merged weekly
  table with preliminary weeks, claims rates, exhaustion rate, duration, checks); added to the workflow
  and confirmed green in run 42408917305 (161 FRED series ok; DOL vs FRED exact match 1995-2026).
  The Thursday wait step has not yet run on a real Thursday schedule; check the first one (2026-11-12).
  DOL's news release PDF (www.dol.gov) blocks automated downloads, so preliminary weeks come from FRED.
- DOL open items: 19 coded columns are still "unclear" in config/dol_columns.csv (none are used in
  calculations); our US exhaustion rate / duration differ from DOL's published US figures by 0.08 pp /
  0.02 weeks for 2026 Q2 while every state matches exactly (cause not yet identified).

## Next steps, in order
Setup steps 1-4 (venv, first fetch, Git, GitHub, first workflow run) are done.
1. Phase 1 continues: Chicago Fed LMI fetcher, data-quality checks (freshness, gaps, outliers), and a
   series-health summary.
2. Then Phase 2: the dashboard MVP on GitHub Pages (see docs/dashboard_requirements.md).

## Where planning lives
The full plan, roadmap and decisions are kept in Troy's Claude project ("Unemployment Correlations"),
in the doc "Unemployment Early-Warning Dashboard — Plan & Roadmap". Big design questions can go back there;
build work happens here. Keep `docs/decisions.md` and the Status section above up to date so both stay in sync.
