# Development dispatcher comparison

Congestion minus distance policy; same scenario hash and horizon within each pair.
These are development scenarios, not an untouched final test set or ML results.

| Layout | Demand | Paired seeds | Mean completed: distance / congestion | Mean completion delta ± sample SD | Mean latency delta* |
|---|---|---:|---:|---:|---:|
| bottleneck | heavy | 5 | 43.40 / 42.80 | -0.60 ± 1.95 | -0.95 |
| bottleneck | light | 5 | 22.80 / 22.60 | -0.20 ± 0.45 | -0.08 |
| medium | heavy | 5 | 33.40 / 32.80 | -0.60 ± 1.34 | -1.84 |
| medium | light | 5 | 19.80 / 19.80 | 0.00 ± 0.00 | 0.60 |
| small | heavy | 5 | 44.80 / 40.60 | -4.20 ± 7.76 | -5.54 |
| small | light | 5 | 23.00 / 23.20 | 0.20 ± 0.45 | -0.15 |

*Completed-only latency: interpret with completion fraction/backlog in runs.csv.
A lower latency can reflect preferential completion of easy jobs. SD describes paired
variation, not a confidence interval or proof of statistical significance.

Recorded collision violations: 0.
Planner, candidate construction, and scoring wall times are reported separately.
Closure request schedules match; actual activation times may differ with occupancy.
Infeasible pairs and jobs excluded by the shared candidate cap are logged per tick.
Heuristic constants are fixed; no tuning against these results was performed.
