# Dashboard requirements

Requirements the Phase 2 dashboard must meet. Add new ones here with the date; record the reasoning
for design decisions in `docs/decisions.md`.

## DOL claims rates (added 2026-11-07)

1. Chart the **SA initial claims rate** and the **SA continuing claims rate**
   (`data/processed/dol/claims_rates_weekly.csv`: `ic_rate_sa`, `cc_rate_sa`, in percent of covered employment).
   - Long history: the full series from 1995.
   - Recession shading for NBER recessions in the window (2001, 2007-09, 2020).
   - Preliminary weeks visibly marked: weeks whose `source_initial` / `source_continued` is
     "news release, advance" or "news release, revised" must look different from "ETA 539" weeks
     (e.g. hollow markers or a dashed segment), with a legend note that they are preliminary and will be
     replaced by the official ETA 539 figures.

## Downloads (added 2026-11-07)

2. Every DOL series and the merged weekly table must be downloadable as **CSV and XLSX**:
   - `national_weekly.csv` (merged table, with its source columns)
   - `national_weekly_eta539.csv`, `seasonal_factors.csv`
   - `claims_rates_weekly.csv`, `exhaustion_duration_monthly.csv`, `benefit_duration_quarterly.csv`
   - `ar539.csv`, `ar5159.csv`, `ar218.csv` (state detail; plain column names)
   - Each download should include, or link to, the column descriptions in `config/dol_columns.csv`.

Note (2026-11-07): on the site the SA initial claims rate is shown per 10,000 covered workers
(`ic_rate_sa` x 100) and the continuing claims rate in percent, per docs/phase2_design.md decision 2.
The data files keep percent.

## Overview first screen (added 2026-11-12, review WP7)
- The Overview opens with "Where things stand": claim frequency (new claims vs. their low of the past year),
  claim severity (people on benefits vs. a year ago, with the Duration watch word) and the early warning, each with
  a status word, the level at which it would turn amber / red, "What it means" and "What to watch".
- Tiles are grouped by frequency and severity; no Sahm tile. "What changed this week" puts unusual moves first and
  merges ordinary ones into one line.
- Charts with an important limit show it as a caveat under the chart; long footers fold into "Source and method".
- Outlook shows "Three things to know" and "How to use the colours" without clicking.
