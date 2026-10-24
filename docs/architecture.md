# Architecture and decisions

The numerical core runs without a browser or server. Exogenous scenario generation
finishes before policy execution. Current observations feed shared candidate
construction and dispatch; the reservation planner proposes movement, and the
simulator checks invariants before simultaneous commitment.

| Module | Responsibility |
|---|---|
| scenario.py | Versioned inputs and seeded schedules |
| planning.py | A* and bounded space-time reservations |
| simulation.py | Lifecycle, service, closures, invariants and trace |
| dispatch.py | Observations, candidates, greedy matching and heuristics |
| datasets.py | Geometry/run splits and observational collection |
| models.py | Fitted regressors, batched inference and bounded JSON |
| learning.py | Validation selection, freeze and held-out evaluation |
| console.py | Locked runtime, replay/persistence and background worker |
| web.py | Loopback FastAPI boundary and SSE snapshots |
| frontend/src | React controls and views of actual backend state |

Greedy dispatch keeps assignment semantics understandable and equal across
policies; it is not globally optimal. Conservative planning retains stationary
fallbacks for unplanned robots and trades completeness for bounded explicit
behavior. Regression asks an interpretable question; mixed findings show why
individual duration estimates do not necessarily optimize a fleet objective.

Whole layout/run separation and training-only preprocessing avoid trajectory-row
leakage. The model freezes before final rollouts. Censored jobs are excluded from
ordinary regression labels but retained in system summaries.

The server clock owns logical time; React only renders snapshots. A second worker
runs bounded comparisons and checks cancellation each tick. Restart reconstructs
the saved scenario/tick/policy/model combination. CPU timings can differ on replay.
The local HTTP boundary is not production authentication or physical validation.
