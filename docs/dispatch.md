# Dispatch and paired experiment semantics

## Current-state boundary

The dispatcher creates an immutable observation containing only the current
tick, currently passable cells, robot positions and current availability, released
queued jobs, service duration, and the number of assigned jobs. Current closure
activations/expirations are applied before this observation. No future releases,
pause end times, closure schedules, completed durations, or rollout outcomes are
passed to a policy scorer. Both heuristic scorers receive the same Candidate
objects. This is a programming boundary for trusted local code, not a sandbox
against malicious Python plugins.

## Common candidate construction

Only unassigned robots that are not currently paused are available. Select up to
32 oldest queued jobs, using (release tick, job ID) ties. The cap is configurable
from 1 to 256. Construct every available robot/job pair in this selected set.
Require a static path from robot to pickup and pickup to delivery through
currently open cells. Other robots are not permanent walls in this reachability
check: their positions influence congestion scores, while the common movement
planner handles actual reservations. Static feasibility does not guarantee that
the fleet can complete an assignment.

All policies use the same cap and reachability checks. Audits count feasible
pairs, infeasible pairs, excluded queued jobs, available robots, and assignments
on every tick, including ticks with no assignment. A cap can delay an otherwise
feasible newer job behind temporarily infeasible old jobs; this is a documented
shared limitation, not an implicit exclusion favorable to one policy. Different
policies eventually occupy different states, so their later candidate sets need
not be identical. The candidate construction rule is identical.

## Scores and matching

- Distance: max(1, empty distance) + max(1, loaded distance) + 2 × service ticks.
  The minimum-one terms reflect arrival transitions at already occupied endpoints.
- Congestion: distance score + 4 × occupied route cells + nearby robots.
  Count other robots on the union of the two deterministic shortest paths;
  nearby means within Manhattan distance one of any route cell. Each other robot
  contributes at most once to each count. These are fixed heuristic weights,
  not fitted parameters or proven delay estimates.
- For both, subtract aging_weight × queued age, default 0.1 tick per waiting tick.
  Aging reduces starvation risk; it does not guarantee bounded waiting.

Sort by (aged score, release tick, robot ID, job ID), then greedily accept pairs
without reusing robots or jobs. Scores are computed from the same pre-assignment
state, rather than recomputing features after each greedy selection. A nonfinite
score or unexpected assignment rejection raises an error; it is not silently
discarded. Future learned-policy fallback behavior will be added with the model.

## Reproduction and evidence

```sh
./run.sh --policy distance
./run.sh --policy congestion --output runs/congestion-demo
./compare.sh --quick --output runs/comparison-quick
./compare.sh --output runs/comparison-full
```

Comparison output must be a new or empty directory. Each paired scenario is
serialized once with a SHA-256 hash, then passed unchanged to both policies.
Policies share simulation horizon, arrival stream, requested closures, temporary
pause schedule, robot count, candidate cap, aging, and the movement/recovery code.
Execution order alternates by seed to reduce systematic wall-time ordering bias.
Closures activate only when unoccupied, so actual activation can differ by policy.

Full section-two mode uses three layouts, two loads (one release every 8 or 2
ticks), five development seeds 0–4, four robots, and 200 ticks: 30 paired scenarios
and 60 runs. Quick mode uses two layouts, three seeds, and 160 ticks: 12 pairs.
These seeds and layouts are development evidence and must not be relabeled as
untouched final ML tests. Future evaluation needs a separate layout/seed manifest.

Outputs include runs.csv, paired.csv, report.md, source-file hashes and config
manifest, full scenarios, and per-run summaries, candidate audits, selected
features, assignment/delivery events, per-job outcomes/censoring, and actual
closure activation logs. Completed results checkpoint after each run. Ctrl-C
records a cancelled manifest; a partial pair is not a valid paired result.

Paired deltas are congestion minus distance. Summaries report mean and sample
standard deviation of completion deltas; they are descriptive and do not claim
statistical significance. Completed-only latency is always presented with
completion/backlog evidence. Waiting includes service, pauses, and movement
waiting for assigned robots. Planner, feature/candidate construction, and scoring
wall times are separate. Trace recording is disabled for batch runs to avoid
storing every tick's full state; tests verify this does not affect dynamics.
