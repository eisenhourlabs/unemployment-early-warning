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
  overwrites revised history and logs the revision in `docs/data_revisions.md`. Backtests use current-vintage
  claims, cut back by their release lag (plan decision 5); FRED's claims vintages (from 2009 only) are used just to
  measure and state the revision effect. Revised monthly series use ALFRED vintages via `src/model/realtime.py`.
- DOL state files (ar539 / ar5159 / ar218) start in 1995; the national ETA 539 report starts in 1971, when
  covered employment (the claims-rate denominator) begins. Rates before 1978 are not strictly comparable
  (UI coverage expansion); the rate charts mark it.
- Thresholds and model weights come from backtests (2001, 2008, 2020 and recent data). Record every
  decision and its reason in `docs/decisions.md`.
- Verify current release dates and series status before stating them; data and schedules change.
- Ask before anything hard to undo: deleting files, rewriting Git history, changing repository settings.

## Layout
| Path | Purpose |
| --- | --- |
| `config/series_catalog.csv` | Every series: source, fetcher, frequency, tier, role, page, history_start (optional; FRED default 1990), status (active/future) |
| `config/state_weights.csv` | Footprint ranking by state (44 states, rank only; exact weights in `internal/`) |
| `config/dol_columns.csv` | DOL coded column names -> plain names, with how each was confirmed (verified / label / inferred / unclear) |
| `src/fetchers/fred_fetcher.py` | Downloads all active FRED series (incl. per-state series) to `data/processed/` |
| `src/fetchers/dol_*.py` | DOL pipeline: `dol_national.py` (ETA 539), `dol_state.py` (ar539/ar5159/ar218), `dol_recent_weeks.py` (merged table + preliminary weeks), `dol_common.py` (shared) |
| `src/fetchers/wait_for_claims.py` | Thursday run: waits up to 60 min for the claims release on FRED; never fails |
| `src/fetchers/release_calendar.py` | Next release dates (FRED schedules + Chicago Fed schedule page) -> `data/processed/release_calendar.csv`; never fails |
| `src/fetchers/chicagofed_fetcher.py` | Chicago Fed Labor Market Indicators: 36 series to `data/processed/CFLMI*.csv` (with vintages) |
| `src/checks/data_quality.py` | Stale / gaps / outlier / fetch checks for every series -> `data/processed/series_health.csv`; fails only on a stale or missing Tier 1 series |
| `config/quality_rules.csv`, `config/quality_dol_columns.csv` | Data-quality settings: allowed ages, known gaps, skips, outlier window and threshold; which DOL columns to check |
| `src/transforms/dol_rates.py` | Claims rates, 12-month exhaustion rate, average duration |
| `src/checks/dol_checks.py` | DOL vs FRED (fails run above 1%); SA continuing claims rate vs DOL IUR (report only) |
| `data/processed/dol/` | DOL outputs (latest figures only) |
| `docs/data_revisions.md` | Automatic log of DOL revisions |
| `docs/dashboard_requirements.md` | What the Phase 2 dashboard must show |
| `src/alerts/alerts.py` | Optional alerts (off) |
| `src/model/` | Phase 3 modeling: `build_claims_history.py` (claims table from 1967), `alfred_fetcher.py` (past vintages), `realtime.py` (`as_known_on(series, date)` + Sahm check), `events.py` (event definition and list), `plot_events.py` (review chart), `current_fetcher.py` (long histories of never-revised series), `triggers.py` (8 Layer 1 triggers monthly, real-time), `backtest_triggers.py` (leads, false alarms, adds-warning), `plot_triggers.py` (status chart), `features.py` (score inputs), `score.py` (early-warning score: fit, out-of-sample test, sensitivity runs), `plot_score.py` (score charts), `score_followups.py` (3d Part A: drivers, NSA claims test, calibration, colour stability, 3/12-month scores), `forecast.py` (fans: baseline + event-path mixture, backtest, stress paths), `nowcast.py` (next UR release), `benchmarks.py` (FOMC SEP / SPF comparison), `plot_forecast.py` (forecast charts) |
| `config/model_series.csv`, `config/event_notes.csv`, `config/triggers.csv` | Modeling series: ALFRED / first-release / current vintage, release lag; Troy's event rulings and notes; Layer 1 trigger thresholds |
| `data/model/` | Modeling data: `claims_weekly.csv`, `alfred/` (vintages + coverage), `current/` (GS10, TB3MS, T10Y3MM full history), `events.csv`, `event_flags_monthly.csv`, `claims_leg_weekly.csv`, `triggers_monthly.csv`, `trigger_episodes.csv`, `trigger_leads.csv`, `trigger_summary.csv`, `status_comparison.csv`, `features_monthly.csv`, `score_*.csv`, `forecast_*.csv`, `stress_paths.csv`, `nowcast.csv`, `benchmark_summary.csv` |
| `docs/model.md`, `reports/` | Phase 3 method and results (grows each stage); review charts (not on the site) |
| `src/signals/`, `src/forecast/` | Phase 3: triggers, composite score, forecast fan |
| `src/site/build_site.py` | Builds the "Unemployment Watch" website (Plotly + Jinja2) into `site/`: shared frame, renders each page |
| `src/site/common.py` | Shared site pieces: data reading, formats, statistics, recession shading, chart builders |
| `src/site/overview.py`, `job_losses.py`, `duration.py`, `leading.py` | One module per page: its charts, tiles, tables and text |
| `src/site/about.py` | About page: definitions, sources (from the catalog), updates, revisions, method notes, disclaimer |
| `src/site/downloads.py` | Data & Downloads page: writes every CSV / XLSX and bundle under `site/data/` (public licences only) |
| `config/derived_columns.csv` | Descriptions of the columns we calculate in DOL files (used in download Columns sheets) |
| `src/site/templates/`, `src/site/static/` | Templates (`base.html` = shared frame, `_macros.html` = chart card, `charts_page.html` = chart-grid pages) and the site's CSS / JavaScript (time control, dark mode, downloads) |
| `site/` | Built website (not committed; rebuilt and published to GitHub Pages by the workflow) |
| `src/checks/check_site.py` | Browser check of the built site (Playwright + Edge; PC only, `requirements-dev.txt`) |
| `docs/phase2_design.md` | Approved Phase 2 design (pages, charts, conventions, time control) |
| `.github/workflows/refresh-data.yml` | Scheduled cloud refresh (weekday mornings + Thursday after claims), then build + publish the site |
| `.github/workflows/publish-site.yml` | Rebuild + publish the site (no data fetch) when site code, config or requirements change on main |
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
- Chicago Fed: `python src\fetchers\chicagofed_fetcher.py`
- Series health (run last): `python src\checks\data_quality.py`
- Release calendar: `python src\fetchers\release_calendar.py`
- Build the site: `python src\site\build_site.py`; preview: `python -m http.server 8000 --directory site`,
  then open http://localhost:8000 (Ctrl+C stops the server)
- Check the built site in a browser (once: `pip install -r requirements-dev.txt`): `python src\checks\check_site.py`
- Phase 3 modeling data, in order: `python src\model\build_claims_history.py`, `python src\model\alfred_fetcher.py`
  (~3 min), `python src\model\current_fetcher.py`, `python src\model\realtime.py` (Sahm check), `python src\model\events.py`,
  `python src\model\plot_events.py`, `python src\model\triggers.py` (~15 s), `python src\model\backtest_triggers.py`,
  `python src\model\plot_triggers.py`, `python src\model\features.py` (~2 min), `python src\model\score.py` (~2 min),
  `python src\model\plot_score.py`, `python src\model\score_followups.py` (~2 min), `python src\model\forecast.py` (~4 min),
  `python src\model\nowcast.py`, `python src\model\benchmarks.py <path to SPF medianLevel.xlsx>`, `python src\model\plot_forecast.py`

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

- 2026-11-07: Phase 1 finished and confirmed green in the cloud (run 42413581523): FRED IDs verified; RPLS / GTRENDS / WARN / CHALLENGER set to
  future; Chicago Fed LMI fetcher (36 series); data-quality checks + series-health summary (211 series:
  206 OK, 5 skipped, 0 WARN, 0 FAIL on 2026-11-07). DOL open items accepted (see docs/decisions.md).
- Still to watch: first real Thursday run (2026-11-12); ETA 539 national allowed age (42 days) is based on
  one observation; Chicago Fed terms of use before offering its data as downloads.

- 2026-11-07: Phase 2 ("Unemployment Watch", design in docs/phase2_design.md) Stage 1 built: site frame,
  Overview page, USREC + history_start in the catalog, release calendar, build + deploy jobs in the workflow.
  Browser check passes locally (desktop, phone, dark mode, time control, downloads). GitHub Pages switched
  on (Source: GitHub Actions); first publish green in run 42438518785 (refresh, build, deploy).
  Live site: https://eisenhourlabs.github.io/unemployment-early-warning/
- 2026-11-07: Stage 1 review fixes live (run 42439932036). Stage 2 built locally: Job Losses page (7 charts),
  PAYEMS / UEMPLT5 history from 1948, site code split into page modules; browser check passes on both pages.
  Reviewed by Troy and live (run 42441206087).
- 2026-11-07: Stage 3 built locally: Duration page (7 charts; average benefit duration = all-claimant weeks paid
  vs. ETA 218 weeks entitled); CC4WSA from 1967, UEMPMED / LNS13025703 from 1948. Browser check passes on all
  three pages. Reviewed by Troy and live (run 42442110406).
- 2026-11-07: Stage 4 built locally: Leading Indicators page (catalog-driven summary table + 8 charts). Licence
  scan of FRED notes: ICE high-yield spread dropped (restricted; files removed, NFCICREDIT added instead);
  U. Michigan sentiment charted with citation, no downloads. Browser check passes on all four pages.
  Reviewed by Troy and live (run 42443436321).
- 2026-11-07: Stage 5 built locally: Data & Downloads page (170 series / files as CSV + XLSX, 6 bundle files,
  346 download files, ~60 MB in site/data/; licence exclusions listed). Browser check compares every CSV with its
  source and opens every XLSX. Reviewed by Troy and live (run 42445260168).
- 2026-11-07: Stage 6 (About page) reviewed and live (run 42446643167). Phase 2 is complete: six pages live at
  https://eisenhourlabs.github.io/unemployment-early-warning/
- 2026-11-08: Phase 2 review fixes (Troy's 10-item list) done and browser-checked on all six pages: no state
  counts or "footprint" on public pages (checked automatically), "state UI claims" wording with IUI spelled out only
  in "why it matters" lines, claims rates from 1971 with the 1978 coverage marker and "(start of data)" wording,
  card wording, sentiment lag note (TEMPHELPS verified against FRED), About fixes, calendar without "After that" /
  Chicago Fed, new "Publish site" workflow, data dictionary + Data table changes, pre-recession reference lines,
  risk-ordered Leading table. Also fixed a redraw feedback loop found while testing (drag-zoom listener).
- Watch: on 2026-11-08 ~03:55 UTC oui.doleta.gov briefly failed its certificate check (hostname mismatch) from
  this PC; it passed again minutes later. If a DOL step fails in a run, check this first.

- 2026-11-08: Phase 3 plan approved (docs/phase3_plan.md). Stage 3a built locally on branch `phase3a` (not pushed,
  website unchanged): claims table from 1967 (rates from 1971; DOL has no covered employment before 1971), ALFRED
  vintages for 7 monthly series (TEMPHELPS / JOLTS only from 2010-11, PERMIT from 1999), `as_known_on` (matches
  FRED SAHMREALTIME in 97.7% of months), event list: 15 events since 1967 (8 recession-linked, 6 scares, 2020
  excluded from fitting), docs/model.md, reports/events.png. Troy's rulings applied the same day (scares count;
  #4 starts Oct 1979; #7 early signal; #10 scare; in config/event_notes.csv). Troy reviewed the list in his
  Claude project.
- 2026-11-08: Stage 3b built locally on `phase3a` (not pushed, website unchanged): 8 Layer 1 triggers monthly since 1967
  on real-time data where it exists (Sahm, yield curve real-time throughout; temp help / manufacturing / NFCI revised
  before 2011-15; claims current-vintage), backtest of leads and false alarms, overall status chart
  reports/layer1_status.png, docs/model.md section 4. Drop candidates flagged, nothing dropped.
- 2026-11-08: Stage 3b review decisions applied (docs/model.md 4.8): "still on within 3 months" rule kept; panel = core 1 Sahm,
  2 claims vs. 52-wk low, 4 continued claims + 6 yield curve (long lead) and 8 NFCI (real-time only since 2011); 3 removed;
  5 temp help and 7 manufacturing = context only (Leading page, stage 3e); all 8 stay 3c score candidates. New overall rule:
  red if 1, 2 or 4 red; amber if one of 1, 2, 4 amber/red AND another panel trigger amber/red. Compared with the plan rule:
  amber 8% vs. 14% of months, longest amber run 9 vs. 17 months, amber false alarms 2 vs. 4. Layer 1 locked (approved).
- 2026-11-08: Stage 3c built locally on `phase3a` (not pushed, website unchanged): early-warning score (ridge logistic,
  8 inputs, real-time), out of sample 2000-2026 Brier 0.114 / skill +0.14 (equal-weight +0.12, Layer 1 +0.01); amber 19%,
  red 50%; sensitivity runs incl. claims vintages (2022 false red hidden by revised claims) and an extra
  coefficients->=0 run (+0.18); docs/model.md section 5, reports/score_history.png, score_reliability.png.
- 2026-11-08: Stage 3c review applied (docs/model.md 5.10): FINAL score = ridge logistic on the 8 trigger measures,
  weights >= 0, amber 20%, red 50%; out of sample 2000-2026 Brier 0.108, skill +0.18; JOLTS tested and left out (made it
  worse); temp help kept; claims-revision effect to be stated, not modeled. Latest score (Oct 2026) 2.4%, green.
- 2026-11-08: Stage 3c approved; branch phase3a pushed to GitHub (origin/phase3a; main and site unchanged).
- 2026-11-08: Stage 3d built locally on phase3a (not pushed, website unchanged), docs/model.md section 6: score
  follow-ups (A1 drivers 2024-26; NSA claims not adopted; recalibration not adopted, verbal bands proposed; hysteresis
  proposed; 3/12-month scores skill +0.22/+0.21) and forecast fans (UR 3/6/12 and continuing claims 13/26 wk pass the
  gate; continuing claims 52 wk fails; initial claims fans no real gain; nowcast ratio 0.90; SPF / FOMC beat our point
  forecasts). Stopped at the gate.
- 2026-11-08: Stage 3d complete (decisions delegated by Troy; model.md 6 "Stage 3d decisions (final)"): verbal bands
  above 35%, colour hysteresis 20/15 and 50/40, initial-claims fans not shown, in-progress rule needs 3 months,
  nowcast shown, FOMC SEP marker allowed. Site shows: UR fans 3/6/12, continuing claims fans 13/26 wk, nowcast,
  stress paths, score.

## Next steps, in order
Setup (steps 1-4), Phase 1, Phase 2 and the Phase 2 review fixes are done and live.
1. Stage 3e (site), plan with Troy first, when he says to start. Push phase3a / merge to main only when he says so.
   Use docs/model.md section 6 "Stage 3d decisions (final)" for what the site shows and how.
2. Stage 3e per docs/phase3_plan.md. Stage 3e must also: show trigger signal colors for the panel (yield curve
   labeled "long lead, often 12+ months"; NFCI caveat "real-time only since 2011"); move temp help and manufacturing
   surveys to the Leading page as context only (not counted in the overall status); use the new overall rule; state
   the claims-revision effect on the methodology page (docs/model.md 5.10); move scikit-learn from
   requirements-dev.txt to requirements.txt so the cloud can compute the score; show only the forecast horizons that
   passed the gate (docs/model.md section 6), 12-month labeled lower confidence; stress paths labeled as what-ifs.
Open items to watch: first real Thursday run (2026-11-12); ETA 539 allowed age (42 days); Chicago Fed LMI terms of use;
DOL certificate glitch seen once on 2026-11-08.

## Where planning lives
The full plan, roadmap and decisions are kept in Troy's Claude project ("Unemployment Correlations"),
in the doc "Unemployment Early-Warning Dashboard — Plan & Roadmap". Big design questions can go back there;
build work happens here. Keep `docs/decisions.md` and the Status section above up to date so both stay in sync.
