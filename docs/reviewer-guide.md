# Explain it and demonstrate it

Think of robots as delivery drivers on a tiled floor. Dispatch chooses the jobs;
a separate planner prevents two drivers entering the same tile or swapping
through one another. We test shortest trip, a traffic penalty, and a learned trip
duration estimate against the same inputs. Better predictions need not improve
the whole fleet.

## Ten reviewer questions

1. **What is the AI?** A fitted numerical duration regressor, not a chatbot; the
   bundled model is a 24-tree forest with real batched prediction calls.
2. **What is learned?** Residual delay above travel/service duration, using current
   distances, congestion, queue/fleet state and topology summaries.
3. **Where are labels from?** Completed simulated assignments. Unfinished jobs
   retain censored lower bounds and remain in fleet accounting.
4. **How is leakage limited?** Whole geometries/run seeds are split; future inputs
   and targets are excluded from features; model selection precedes final rollouts.
5. **How is movement protected?** Shared vertex/reverse-edge reservations, station
   occupancy, stationary fallbacks and assertions before movement commitment.
6. **Can it deadlock?** Yes. Bounded prioritized planning is incomplete. Yielding is
   attempted; unresolved jobs remain visible rather than being teleported away.
7. **Is comparison fair?** Shared hashes, horizons, arrivals, candidate rules,
   planner and recovery; actual closure activation can depend on occupancy.
8. **Does ML win?** Not consistently. Ordinary results fall between the heuristics;
   stress performance is weaker. No test-driven tuning changed those findings.
9. **Is it physical robotics?** No. There is no hardware/dynamics validation or
   claim of deployed robots, real warehouse savings, or broad generalization.
10. **What did AI assist?** Codex substantially generated/tested the implementation
    and docs. Ownership does not imply manual authorship of every component.

## 90-second demo

- **0–15s:** State the duration-prediction/dispatch question and simulation-only scope.
- **15–35s:** Play timed closure. Point out robots, targets, paths, completion and backlog.
- **35–50s:** Pause/step and show the two policies sharing a movement planner and inputs.
- **50–65s:** Show model identity, training/censoring counts and split methodology.
- **65–80s:** Show 2,192 learned completions versus 2,156 distance and 2,241 congestion;
  explain that stress results are worse and no universal gain is claimed.
- **80–90s:** Show reproduction, test evidence, model card and one limitation.

## Truthful portfolio wording

“AI-assisted project: warehouse fleet simulator and dispatch console; evaluated
learned duration ranking against two heuristics across 270 simulated runs,
reporting mixed throughput, unfinished work and zero observed vertex/edge
collision violations.” Implementation/documentation were substantially generated
with Codex. Explain personal contributions and understanding accurately.
