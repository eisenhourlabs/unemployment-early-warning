# Phase 2 Dashboard Design: Unemployment Watch

Approved by Troy, November 7, 2026. This is the build brief for Phase 2.
Updated November 7, 2026 (Stage 1 review): DOL claims-rate history starts in 1995, not 1967.

## Summary

Phase 2 ships Unemployment Watch, a six-page static website on GitHub Pages: Overview, Job Losses, Duration, Leading Indicators, Data & Downloads, and About. Every chart and download reads from the same data files the pipeline already produces, so the site rebuilds itself after each data refresh with no manual step.

- **Built with:** Python + Plotly charts + simple HTML templates. All Python, so you can read and maintain it, with interactive charts and no server to run (details below).
- **Headline measures:** the SA initial claims rate and SA continuing claims rate from the DOL data, with weekly history back to 1995 (the start of our DOL data) and recession shading, alongside the unemployment rate.
- **The state map** comes in Phase 4. The **early-warning score and forecast fan** arrive in Phase 3; the Overview leaves room for them now.
- **All decisions are settled** (table at the end), including a page-wide time control that opens charts on the last 5 years.

Nothing here is code yet. Build it in stages and check each stage with Troy.

## Site structure and shared layout

Every page shares the same frame, so a reader always knows how fresh the data is and where to go next.

| Element | What it shows |
| --- | --- |
| Top bar | "Unemployment Watch" on the left; page links: Overview · Job Losses · Duration · Leading · Data · About; dark-mode toggle on the right |
| Freshness line and time control | "Data through: claims week ending … · unemployment rate … · site updated …", plus a warning badge if any series is stale (from the health check). Below it, the page time control (default 5Y) |
| Page body | One column on phones, a 2-column grid of chart cards on wider screens, max width about 1,200 px |
| Chart card | Title stating what the chart shows, a one-line "why it matters", the chart, source and units, and buttons for Download CSV and Download image |
| Footer | Sources, "Not an official forecast; public data only" disclaimer, link to the GitHub repo |

**Overview page layout (desktop, top to bottom):**

```
+--------------------------------------------------------------------------+
| Unemployment Watch        Overview · Job Losses · Duration · Leading ·    |
|                           Data · About · [dark-mode toggle]               |
+--------------------------------------------------------------------------+
Data through … · updated …  |  Time: 1Y · 2Y · [5Y] · 10Y · 20Y · Max ·
                               2001 · 2008–09 · 2020 · Custom
+------------------------+  +----------------------------------------------+
| Early-warning score    |  | What changed this week                       |
| (dashed placeholder    |  | 3–5 auto-written sentences from fixed rules  |
|  until Phase 3)        |  |                                              |
+------------------------+  +----------------------------------------------+
+------------+ +------------+ +------------+ +------------+ +------------+
|Unemployment| |Initial     | |Initial     | |Continuing  | |Sahm        |
|rate        | |claims 4-wk | |claims rate | |claims rate | |indicator   |
|latest+chg  | |latest+chg  | |+percentile | |+percentile | |vs 0.50     |
+------------+ +------------+ +------------+ +------------+ +------------+
+--------------------------------------------------------------------------+
| Unemployment rate, last 5 years (recession shading; Phase 3 forecast fan) |
+--------------------------------------------------------------------------+
+------------------------------------+ +-----------------------------------+
| SA initial claims rate             | | SA continuing claims rate         |
| per 10,000 covered workers         | | percent of covered workers        |
+------------------------------------+ +-----------------------------------+
| Next releases: claims Thu · jobs report · JOLTS · Chicago Fed  Download → |
Footer: sources · not an official forecast; public data only · GitHub repo
```

On a phone the same blocks stack in one column, in this order. The dashed box is the Phase 3 placeholder.

## Pages and charts

24 charts across four content pages. Job Losses covers frequency (new job losses) and Duration covers severity (how long unemployment lasts), the two things that drive IUI claims. Leading Indicators shows what tends to move first. Every time-series chart opens on the **last 5 years**, adjustable from the page's time control (see Chart conventions).

### 1. Overview — "Where are we this week?"

| Element | Series | Why |
| --- | --- | --- |
| Early-warning score panel | Placeholder: "Arrives in Phase 3" | Reserves the top-left spot so the layout doesn't change later |
| 5 headline tiles | Unemployment rate; SA initial claims (4-wk avg); SA initial claims rate; SA continuing claims rate; Sahm indicator. Each shows latest, change vs. prior period and vs. a year ago, and percentile on full history: since 1995 for the two claims rates (DOL data), 1967 for SA initial claims (FRED), 1948 for the unemployment rate | Answers "how unusual is this?" in one glance |
| "What changed this week" | 3–5 auto-written sentences from fixed rules, e.g. "SA initial claims rose 8,000 to 228,000, the highest since March" | Gives the news without reading charts |
| Unemployment rate | UNRATE with recession shading; forecast fan added in Phase 3 | The headline everyone knows |
| Claims rates, small pair | SA initial claims rate and SA continuing claims rate | The two IUI drivers |
| Release calendar | Next claims, jobs report, JOLTS and Chicago Fed dates | Tells readers when it will change |

### 2. Job Losses — frequency

| # | Chart | Series | Why |
| --- | --- | --- | --- |
| 1 | SA initial claims rate | DOL weekly report ÷ covered employment; news-release weeks marked preliminary | The headline frequency measure |
| 2 | SA initial claims, 4-week avg bold with weekly faint | ICSA / DOL weekly report | Week-to-week detail |
| 3 | NSA initial claims, this year vs. prior 3 years | DOL weekly report NSA, by week of year (fixed: calendar year view) | Checks seasonal adjustment |
| 4 | Initial claims, % change vs. a year ago (4-wk avg) | Derived | Turns a level into a warning signal |
| 5 | Payroll change, monthly bars with 3-month average | PAYEMS | Net job creation |
| 6 | JOLTS layoffs & discharges rate | JTSLDR | Layoffs from the employer side |
| 7 | Newly unemployed (< 5 weeks) | UEMPLT5 | Fresh inflow from the household side |

### 3. Duration — severity

| # | Chart | Series | Why |
| --- | --- | --- | --- |
| 1 | SA continuing claims rate | DOL weekly report ÷ covered employment, checked against DOL's published insured unemployment rate | The headline severity measure |
| 2 | SA continued claims, 4-week avg bold with weekly faint | CCSA / DOL weekly report | Detail |
| 3 | Exhaustion rate, 12-month | DOL monthly claims and payments report (ETA 5159) | Share running out of benefits |
| 4 | Average benefit duration | DOL quarterly benefit rights report (ETA 218) | Closest public match to IUI benefit months |
| 5 | Median weeks unemployed and share 27+ weeks | UEMPMED, LNS13025703 | Household-survey duration |
| 6 | JOLTS hires rate | JTSHIR | Low hiring means longer spells |

### 4. Leading Indicators — simple version

A summary table on top, then a grid of small charts. No signal colors yet; Phase 3 adds those once thresholds are backtested.

| Element | Series | Why |
| --- | --- | --- |
| Summary table | One row per indicator: latest value, 3-month change, percentile since 1990, direction arrow, typical lead time | One glance at what's moving |
| Yield curve, 10-year minus 3-month | T10Y3M, with a zero line | Inversion has preceded past recessions |
| Temporary help jobs, % change vs. a year ago | TEMPHELPS | Firms cut temps first |
| Average weekly hours, manufacturing | AWHMAN | Hours fall before headcount |
| Building permits | PERMIT | Housing turns early |
| Regional manufacturing surveys | Philadelphia Fed and Empire State general activity, with a zero line | Free stand-in for ISM |
| Consumer sentiment | UMCSENT | Spending and job-loss worries |
| High-yield credit spread | BAMLH0A0HYM2 | Corporate funding stress |
| Financial conditions | NFCI, with a zero line | Broad credit tightness |

### 5. Data & Downloads

A searchable catalog of every series with download buttons (see How downloads work).

### 6. About

Definitions in plain English (SA vs. NSA, covered employment, the two rates), sources, how often each updates, the revision policy (DOL revisions replace history; see `docs/data_revisions.md`), and the disclaimer.

## Chart conventions

The same rules on every chart, so readers learn them once.

**How to express the claims rates.** This is the biggest presentation choice. Worked example from the July 23 release: 187,000 SA initial claims ÷ 153,732,307 covered employment.

| Option | Initial claims rate shows as | Continuing claims rate shows as | Pros / cons |
| --- | --- | --- | --- |
| Weekly percent | 0.122% | about 1.2% | Simple, but initial-claims decimals are tiny and hard to read |
| **Per 10,000 covered workers (initial); percent (continuing)** — recommended | 12.2 per 10,000 per week | about 1.2% | Readable whole numbers; the continuing rate matches DOL's published insured unemployment rate |
| Annualized (weekly rate × 52) | about 6.3% a year | about 1.2% | Familiar to actuaries as an incidence rate, but overstates it because it counts repeat claimants |

**Other conventions**

- **Recession shading:** grey bands from the NBER recession dates (FRED series USREC, to be added to the catalog). NBER announces dates months late, so the newest downturn appears only once it's official.
- **Preliminary weeks:** weeks still coming from the news release show as hollow markers on a dashed segment, with "preliminary (advance)" in the tooltip. They turn solid when DOL's weekly report replaces them.
- **Colors:** one accent color for the main series, grey for comparisons (last year, prior years). Red, amber and green are reserved for the Phase 3 signal so they always mean risk level.
- **Interactivity:** hover shows exact date and value; page time control (below); drag to zoom, double-click to reset; legend clicks hide or show lines.
- **Number formats:** claims in thousands with commas (228,000); rates to one decimal for percent, one decimal for per-10,000; dates as "Nov 1, 2026".
- **Every chart says** its source, units, SA or NSA, and the last data date in its footer.

**Time frame control**

Every page with charts gets one time control at the top that sets all charts on the page at once. Charts open on the last 5 years.

| Control | Options |
| --- | --- |
| Range buttons | 1Y · 2Y · **5Y (default)** · 10Y · 20Y · Max |
| Recession views | 2001 · 2008–09 · 2020. Each shows the full rise and recovery: about a year before the recession through two years after (for 2008–09, Jan 2007 to Dec 2011) |
| Custom | From / To date pickers |

Why 5 years: from today it starts in late 2021, after the 2020 spike. A window that includes 2020 squashes everything else flat, because claims briefly hit about 30 times normal. Five years still shows the full post-pandemic cycle. The 10Y and 20Y buttons and recession views are one click away when you want history.

Rules that come with it:

- **The y-axis rescales to the visible window**, so recent movement stays readable, and jumping to 2008–09 rescales to that period.
- **Each chart can still be zoomed on its own**; double-click returns it to the page setting.
- **Every visit opens on 5Y**, so everyone sees the same default view when sharing a link. The URL records the chosen range, so a link to "2008–09 on the Duration page" opens exactly that view.
- **Tiles and percentiles always use full history**, whatever the window shows.
- **Chart downloads offer both** "visible range" and "full history".
- The NSA seasonal comparison chart is the one exception: it always shows this year vs. the prior three, by week of year.

## Chart library and site technology

Recommendation: **Python builds the whole site, with Plotly for the charts.** It keeps everything in one language you're learning, runs in the existing GitHub Actions job, and needs no server.

| Option | How it works | Interactive charts | Fits GitHub Pages | Learning load for Troy | Verdict |
| --- | --- | --- | --- | --- | --- |
| **Python + Plotly + HTML templates (Jinja2)** | A `build_site.py` script reads the data files, draws charts, fills page templates, writes plain HTML | Yes: hover, zoom, range buttons, image export built in | Yes | Low: Python only, plus simple HTML templates | **Recommended** |
| Observable Framework | Markdown pages with JavaScript charts; Python can feed it data | Yes, very polished | Yes | High: needs Node.js and JavaScript | Best-looking, but a second language to maintain |
| Quarto dashboards | Python code in Markdown documents, rendered to a site | Yes (uses Plotly) | Yes | Medium: another tool to install and learn | Good fallback if templates feel clunky |
| Streamlit or Dash | Python web apps | Yes | No: they need a running server | Low | Ruled out: GitHub Pages hosts static files only |

How it fits the pipeline: after the data refresh, the same workflow runs `build_site.py` and publishes the result to GitHub Pages. If the build fails, the previous site stays up and the run turns red.

Trade-off to know: the Plotly charting library is about 3.5 MB, loaded once per visit from a fast public CDN. Pages may take a second longer the first time on a slow phone connection, which is fine for an internal tool.

## How downloads work

Three ways to get data, all regenerated on every refresh so downloads always match the charts.

1. **From any chart:** a "Download CSV" button gives exactly the series on that chart, in the selected range, and "Download image" gives a PNG for slides.
2. **From the Data & Downloads page:** a searchable, filterable catalog (by page, source, frequency). Each row shows name, series ID, source (linked), frequency, units, SA/NSA, latest date and value, and last updated, with **CSV** and **XLSX** buttons. The XLSX has a second sheet with the series' metadata and source link.
3. **Bundles** for people who want everything at once:
   - **DOL weekly claims (merged):** one table from 1995 with every DOL weekly column, the calculated rates, and the source flag (DOL weekly report vs. preliminary news release). CSV and XLSX.
   - **All weekly series** and **all monthly series**: wide CSVs, one column per series.
   - **Everything workbook:** one XLSX, one sheet per frequency, plus a data dictionary sheet.

**Stable links for Excel.** Each file has a permanent address, e.g. `…/data/series/ICSA.csv` and `…/data/bundles/dol_weekly_claims.csv`. In Excel, **Data → From Web**, paste the link, and **Refresh** pulls the latest. The page will include a short how-to.

**What's not downloadable:** nothing licensed is in Phase 2. When Challenger arrives in Phase 4, it will be charted only. Footprint (branch) weights aren't offered as a download; they're used only inside the state view later.

## Placeholders and what's out of scope

| Item | In Phase 2 | Arrives |
| --- | --- | --- |
| Early-warning score panel | Labeled placeholder on the Overview | Phase 3 |
| Forecast fan on the unemployment rate chart | Chart built so a fan layer can be added | Phase 3 |
| Leading indicators page (yield curve, temp help, hours, permits, surveys) | Built in Phase 2 as a simple version | Signal colors added in Phase 3 |
| States page and map (footprint-weighted) | Not built | Phase 4 |
| Chicago Fed nowcast tile | Added to the Overview if its fetcher is done by build time | Phase 1 fetcher |
| Alerts | Not shown | Phase 3, off by default |
| Consumer credit stress, company data | No | Future (deferred) |

## Decisions (settled November 7, 2026)

| # | Question | Decision |
| --- | --- | --- |
| 1 | Site name | **Unemployment Watch** |
| 2 | Claims rate units | Initial claims per 10,000 covered workers (weekly); continuing claims as a percent |
| 3 | Default chart windows | Replaced by the page time control, default 5 years |
| 4 | Default claims line | 4-week average bold, weekly faint |
| 5 | Implied weeks on benefits | Left out |
| 6 | Leading indicators page | Build a simple version now |
| 7 | Technology | Python + Plotly + HTML templates (Jinja2) |
| 8 | Downloads | CSV and XLSX per series, plus bundles |
| 9 | Look | Clean light theme with a dark-mode toggle |
| 10 | Time frame (added) | Page-wide control: 1Y · 2Y · 5Y · 10Y · 20Y · Max, recession views 2001 · 2008–09 · 2020, custom dates; opens on 5Y |

Next: Claude Code builds it in stages: site frame and Overview first, then Job Losses, Duration, Leading Indicators, Data & Downloads, and About.
