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
- Thresholds and model weights come from backtests (2001, 2008, 2020 and recent data). Record every
  decision and its reason in `docs/decisions.md`.
- Verify current release dates and series status before stating them; data and schedules change.
- Ask before anything hard to undo: deleting files, rewriting Git history, changing repository settings.

## Layout
| Path | Purpose |
| --- | --- |
| `config/series_catalog.csv` | Every series: source, fetcher, frequency, tier, role, page, status (active/future) |
| `config/state_weights.csv` | Footprint ranking by state (44 states, rank only; exact weights in `internal/`) |
| `src/fetchers/fred_fetcher.py` | Downloads all active FRED series (incl. per-state series) to `data/processed/` |
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

## Status (2026-11-06)
- Phase 0 done: folders, catalog (35 active rows), footprint weights, FRED fetcher (tested only against
  mocked API responses), scheduled workflow, alerts module.
- 2026-11-07: `.venv` created; first live full fetch done, all 159 active series OK after one catalog ID fix
  (Empire State, logged in docs/decisions.md).
- NOT yet done: Git repository, GitHub upload, GitHub secret, first workflow run.

## Next steps, in order
1. Create `.venv`, install requirements, run the fetcher for UNRATE ICSA CCSA; check the output looks right
   (latest unemployment rate, claims in the low hundreds of thousands, no errors). Then run the full fetch
   and report any FAILED series (likely a wrong ID in the catalog: fix it and log the fix).
2. Initialize Git, make the first commit (confirm `config/.env` and `internal/` are NOT included).
3. Create the public GitHub repo with the GitHub CLI (`gh repo create`), push, and set the secret with
   `gh secret set FRED_API_KEY` (read the value from config/.env without echoing it).
4. Trigger the workflow (`gh workflow run "Refresh data"`), watch it (`gh run watch`), fix until green.
5. Then Phase 1 continues: DOL weekly-claims backup fetcher, Chicago Fed LMI fetcher, data-quality checks
   (freshness, gaps, outliers), and a series-health summary. Then Phase 2: the dashboard MVP on GitHub Pages.

## Where planning lives
The full plan, roadmap and decisions are kept in Troy's Claude project ("Unemployment Correlations"),
in the doc "Unemployment Early-Warning Dashboard — Plan & Roadmap". Big design questions can go back there;
build work happens here. Keep `docs/decisions.md` and the Status section above up to date so both stay in sync.
