# Shutdown fallback: validation (Phase 4 stage 4c)

Pre-registered 2026-11-09 in docs/decisions.md before any run. Estimates vs. DOL's official SA figures.
Acceptance: median absolute error <= 2% and 90th percentile <= 5%. Selection rule: "scaled" only if it beats "carry" on both the median and the 90th percentile in (b).

## (b) Monte Carlo, 1996 to date: k = 1-5 areas dropped (probability proportional to claims share)

| Measure | Method | Draws | Median abs. error | 90th pct | Max | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| Initial claims | carry | 8,030 | 1.02% | 4.41% | 22.5% | PASS |
| Initial claims | scaled | 8,030 | 0.84% | 3.52% | 20.9% | PASS |
| Continuing claims | carry | 8,030 | 0.35% | 1.75% | 16.6% | PASS |
| Continuing claims | scaled | 8,030 | 0.27% | 1.30% | 14.0% | PASS |

**Selected by the rule:** Initial claims: scaled; Continuing claims: scaled

### By number of areas missing (k), selected method

| Measure | k | Median | 90th pct | Max | Avg. share of claims missing |
| --- | --- | --- | --- | --- | --- |
| Initial claims | 1 | 0.31% | 1.97% | 16.7% | 5.7% |
| Initial claims | 2 | 0.64% | 2.64% | 15.5% | 11.0% |
| Initial claims | 3 | 0.94% | 3.42% | 11.6% | 16.1% |
| Initial claims | 4 | 1.22% | 4.16% | 19.6% | 20.8% |
| Initial claims | 5 | 1.42% | 4.74% | 20.9% | 24.9% |
| Continuing claims | 1 | 0.09% | 0.71% | 12.8% | 5.9% |
| Continuing claims | 2 | 0.20% | 1.11% | 12.7% | 11.4% |
| Continuing claims | 3 | 0.31% | 1.28% | 8.3% | 15.9% |
| Continuing claims | 4 | 0.41% | 1.56% | 12.6% | 21.0% |
| Continuing claims | 5 | 0.50% | 1.65% | 14.0% | 25.5% |

### Excluding March-December 2020 (pandemic surge; information only, not the acceptance basis)

| Measure | Method | Median | 90th pct |
| --- | --- | --- | --- |
| Initial claims | carry | 1.01% | 4.37% |
| Initial claims | scaled | 0.83% | 3.46% |
| Continuing claims | carry | 0.34% | 1.68% |
| Continuing claims | scaled | 0.27% | 1.27% |

### Largest errors (selected method)

| Measure | Week | k | Dropped | Error |
| --- | --- | --- | --- | --- |
| Initial claims | 2017-09-02 | 5 | PA TX AK CO DE | -20.9% |
| Initial claims | 2017-09-02 | 4 | CA TX MO NV | -19.6% |
| Initial claims | 2006-05-06 | 5 | NV MN PR FL AZ | -17.0% |
| Initial claims | 2006-05-06 | 1 | PR | -16.7% |
| Initial claims | 2005-09-10 | 5 | LA OH OR HI TX | -15.8% |
| Continuing claims | 2020-05-16 | 5 | MA FL CA NY IA | +14.0% |
| Continuing claims | 2020-04-25 | 5 | NV CA NY KY WA | -12.9% |
| Continuing claims | 2020-04-25 | 1 | CA | -12.8% |
| Continuing claims | 2020-04-25 | 2 | KY CA | -12.7% |
| Continuing claims | 2020-04-25 | 4 | MO KY CA NC | -12.6% |

## (a) Replay: Oct-Nov 2025 shutdown (no national release for these weeks)

| Filing week | Measure | Week | Missing areas | Basis | Official SA | Carry | Scaled |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-09-27 | Initial claims | 2025-09-27 | AZ MA NV TN CO HI | assumed | 225,000 | 225,234 (+0.10%) | 225,005 (+0.00%) |
| 2025-09-27 | Continuing claims | 2025-09-20 | AZ MA NV TN CO HI | assumed | 1,921,000 | 1,921,803 (+0.04%) | 1,919,047 (-0.10%) |
| 2025-10-04 | Initial claims | 2025-10-04 | AZ MA NV TN CO HI | assumed | 233,000 | 230,766 (-0.96%) | 233,555 (+0.24%) |
| 2025-10-04 | Continuing claims | 2025-09-27 | AZ MA NV TN CO HI | assumed | 1,929,000 | 1,931,061 (+0.11%) | 1,929,748 (+0.04%) |
| 2025-10-11 | Initial claims | 2025-10-11 | AZ MA NV TN | documented | 222,000 | 218,036 (-1.79%) | 218,053 (-1.78%) |
| 2025-10-11 | Continuing claims | 2025-10-04 | AZ MA NV TN | documented | 1,928,000 | 1,932,190 (+0.22%) | 1,929,386 (+0.07%) |
| 2025-10-18 | Initial claims | 2025-10-18 | TN MA CO | documented | 231,000 | 230,789 (-0.09%) | 230,336 (-0.29%) |
| 2025-10-18 | Continuing claims | 2025-10-11 | TN MA CO | documented | 1,947,000 | 1,941,752 (-0.27%) | 1,943,235 (-0.19%) |
| 2025-10-25 | Initial claims | 2025-10-25 | AZ MA NV TN CO HI | assumed | 221,000 | 224,654 (+1.65%) | 224,786 (+1.71%) |
| 2025-10-25 | Continuing claims | 2025-10-18 | AZ MA NV TN CO HI | assumed | 1,953,000 | 1,952,859 (-0.01%) | 1,957,321 (+0.22%) |
| 2025-11-01 | Initial claims | 2025-11-01 | AZ MA NV TN CO HI | assumed | 228,000 | 228,846 (+0.37%) | 230,231 (+0.98%) |
| 2025-11-01 | Continuing claims | 2025-10-25 | AZ MA NV TN CO HI | assumed | 1,962,000 | 1,962,985 (+0.05%) | 1,963,617 (+0.08%) |
| 2025-11-08 | Initial claims | 2025-11-08 | AZ MA NV TN CO HI | assumed | 228,000 | 225,463 (-1.11%) | 227,153 (-0.37%) |
| 2025-11-08 | Continuing claims | 2025-11-01 | AZ MA NV TN CO HI | assumed | 1,946,000 | 1,948,559 (+0.13%) | 1,949,810 (+0.20%) |

| Measure | Method | Median abs. error | 90th pct | Max | Verdict |
| --- | --- | --- | --- | --- | --- |
| Initial claims | carry | 0.96% | 1.71% | 1.79% | PASS |
| Initial claims | scaled | 0.37% | 1.74% | 1.78% | PASS |
| Continuing claims | carry | 0.11% | 0.24% | 0.27% | PASS |
| Continuing claims | scaled | 0.10% | 0.21% | 0.22% | PASS |

Context (not a test): what economists estimated at the time, from the same state data then available:
- Week ending 2025-10-11: about 217,000 (JPMorgan, Goldman Sachs); official SA today 222,000.
- Week ending 2025-10-18: 227,000-232,000 (Goldman Sachs 227k, JPMorgan 229k, Citi / Nationwide 232k); official SA today 231,000.

## Limitations

- Today's state data are revised: real-time errors from later state revisions are not captured, so these errors understate what a live estimate would show.
- The official SA figures compared with are DOL's current published values (DOL revises SA claims each spring).
- Only two shutdown weeks have a documented list of missing areas (Reuters); the others assume the union of the areas named missing at some point.
- One draw per week and k (fixed seed 2026): the pooled statistics rest on about 8,000 draws per measure.
