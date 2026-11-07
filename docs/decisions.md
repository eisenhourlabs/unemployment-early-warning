# Decision log

Record every change to thresholds, model weights, data sources or hosting, with the date and reason.

| Date | Decision | Reason | Decided by |
| --- | --- | --- | --- |
| 2026-11-05 | Project redirected from correlation study to automated early-warning dashboard | Business need: fast read on IUI claim frequency and severity | Troy |
| 2026-11-05 | Primary data source = FRED API; GitHub Actions + static site proposed | Free, ~80% of series in one API, runs without a local PC | Proposed, pending hosting decision |
| 2026-11-06 | Audience internal; hosted publicly on Troy's personal GitHub with no company branding | Personal project; public data only | Troy |
| 2026-11-06 | Free sources only: Indeed, ISM and Conference Board dropped | Licensing cost and republishing limits | Troy |
| 2026-11-06 | Tier 5 (consumer credit stress) and all company data deferred to a future phase | Site is public | Troy |
| 2026-11-06 | Alerts built but switched off (ALERTS_ENABLED=false) | Not needed yet | Troy |
| 2026-11-06 | Forecast priority 3-6 months; 12 months still shown | Pricing and underwriting horizon | Troy |
| 2026-11-06 | States weighted by a 44-state exposure footprint; labeled "footprint" on site, no company name; source kept in internal/ | Proxy for exposure without company data | Troy |
| 2026-11-06 | Troy is maintainer; code written for a Python learner (comments, one script per step) | Troy is learning Python | Troy |
| 2026-11-07 | Catalog fix: Empire State series ID changed from GACDINA066MSFRBNY to GACDISA066MSFRBNY | Old ID does not exist on FRED (it mixed the not-seasonally-adjusted code "INA" with the seasonally-adjusted suffix "MS"); found via FRED series search. Chose the seasonally adjusted version to match the published headline and the Philly Fed row | Claude, during first full fetch |
| 2026-11-07 | Public config/state_weights.csv reduced to a rank per state (footprint_rank, ties share a rank); exact weights kept only in internal/ | Exact weights could be multiplied back to the underlying counts and identify the source. Ranks keep the ordering needed for "top N footprint states" without revealing magnitudes | Troy |
| 2026-11-07 | Fetcher fails the run (exit 1, red GitHub run) if any Tier 1 series fails or more than 10% of all series fail; otherwise passes and prints a failed-series summary | Before, it failed only if every series failed, so partial outages showed green. Tier 1 series are the core claim-frequency and severity inputs; 10% (16 of 159 today) tolerates a few state series lagging or briefly unavailable | Troy |
| 2026-11-07 | Workflow actions bumped: actions/checkout v4 -> v7, actions/setup-python v5 -> v7 (current majors per their GitHub releases) | v4/v5 ran on deprecated Node 20. Release notes reviewed: no breaking change affects this workflow (v6 checkout moved stored credentials to a separate file; data-bot push confirmed working in run 42403686070) | Troy |
| 2026-11-07 | Workflow Python 3.12 -> "3.15" (newest 3.15 patch; 3.15.2 today) | Match the local .venv so local and cloud runs behave the same. Confirmed 3.15.2 is in setup-python's manifest for Ubuntu 22.04, 24.04 and 26.04 | Troy |
