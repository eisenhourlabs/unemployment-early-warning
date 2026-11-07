# Unemployment Early-Warning Dashboard

Automated dashboard showing where US unemployment has been, where it is now versus history,
and a 3/6/12-month forecast range with a green/amber/red layoff-risk signal. Built for consumer-lending and
credit involuntary unemployment (IUI) insurance decisions.

Full plan and roadmap: see the project doc "Unemployment Early-Warning Dashboard - Plan & Roadmap".

## Folder map

| Folder | Holds |
| --- | --- |
| `config/` | `series_catalog.csv` (every series), `state_weights.csv` (footprint ranking by state), `.env` (your keys, never committed) |
| `src/fetchers/` | One Python fetcher per source (FRED, DOL, BLS, Chicago Fed, NY Fed, Google Trends, WARN) |
| `src/signals/` | Rule-based triggers and the composite early-warning score |
| `src/forecast/` | Nowcast, 3/6/12-month forecast ensemble, backtests |
| `src/alerts/` | Optional email/Teams alerts (off by default) |
| `data/raw/` | Raw downloads as received (not committed) |
| `data/processed/` | Tidy series files the site reads |
| `data/vintages/` | Snapshots of each release, for revision tracking and honest backtests |
| `site/` | Dashboard pages |
| `exports/` | CSV/XLSX files offered on the Data & downloads page |
| `.github/workflows/` | Scheduled refresh jobs |
| `docs/` | Decision log, methodology, project instructions |
| `notebooks/` | Exploration and backtest notebooks |
| `tests/` | Data quality checks |

## Status

Phase 1 (data pipeline) in progress. FRED fetcher and scheduled GitHub workflow written; first live run pending.
See `docs/getting_started.md` for setup on Windows.

## Rules

- Never commit API keys; use `.env` locally and GitHub secrets in the cloud.
- Internal company data never goes in this repository or on a public site; private notes live in `internal/` (git-ignored).
- Add new indicators by adding a row to `config/series_catalog.csv`.
