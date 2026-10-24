# Section 1: simulation and reservation semantics

## Time and lifecycle

A snapshot at integer t is the state before the next movement. Jobs released
at t are eligible for external assignment. Policy observation activates eligible
closures before dispatch; a step also applies this idempotent update, then
computes reservations, commits one simultaneous movement, advances service,
checks invariants, and records the snapshot at t+1. The fixed simulation horizon
is the terminal condition; empty queues do not stop the clock early.

Each robot carries at most one assigned job. It travels to pickup, spends exactly
`service_ticks` subsequent ticks loading, travels to delivery, then spends the
same number unloading. On-site assignment still uses an arrival transition tick
before service starts. Completed latency is release-to-delivery completion;
future training targets will be assignment-to-delivery completion. Capacity,
pickup order, unique assignment, and unique completion are asserted.

Pauses prevent movement and service advancement during [start, start+duration).
Idle robots return to their individual parking cell when possible. Stationary
robots, including service and paused robots, occupy their cells.

## Planning

Static A* uses Manhattan distance and deterministic coordinate ties. Space-time
search allows four-neighbor movements and waits. A vertex reservation forbids
two robots in the same cell at a given relative tick. A directed edge reservation
forbids the opposite traversal at the same tick. Goals must remain safely
occupiable through the remaining planning horizon.

Before planning, all robots receive a stationary reservation for the entire
horizon. Robots are replanned sequentially, removing only their own reservations.
Thus even an unplanned robot retains a safe fallback. Priority rotates every
eight ticks. Search caps expansion at 20,000 states per robot, uses deterministic
ties, and returns a safe prefix when the goal lies beyond the horizon. The
fallback frontier favors proximity and low accumulated distance, then fewer
moves. An exhausted search without a horizon frontier records planning failure
and retains the stationary fallback. Only the first action is executed; all plans
are rebuilt next tick. Exported paths are proposals, not movement history.

This conservative approach can miss coordinated solutions. No completeness,
optimality, or universal recovery guarantee is made. Continuous collision
assertions run before movement commitment; failures retain seed/tick in the
error. The caller must preserve the scenario and actions to reproduce a failure.

## Bounded recovery and failure accounting

Progress means a new best Manhattan distance for a job phase, an arrival, or a
service tick; arbitrary motion does not count. After eight and sixteen consecutive
ticks without such progress, one deterministically selected robot attempts to
yield toward its home for eight ticks. The ordinary reservation safety rules
apply. After 24 unproductive ticks, a `fleet_stalled` event includes affected jobs.
Progress after a stall increments `recoveries`. This is a diagnostic heuristic,
not a proof of deadlock: a legitimate long detour can also trigger it, and
repeated motion can continue. `yield_attempt` is logged separately from recovery.

Structurally disconnected pickup/delivery jobs, or jobs unreachable from every
robot's initial component, are marked `impossible`. Temporary closures instead
defer assignment or cause safe waiting. Summaries retain impossible counts,
backlog, and assigned-but-unfinished/censored counts alongside completed latency.
Waiting ticks currently include loading, unloading, pauses, and blocked movement
while a job is assigned; idle parking time is excluded.

## Exogenous inputs

Order endpoints and release times are generated with a private seeded RNG before
the run; simulation and dispatch consume no RNG. Small, medium, and bottleneck
presets share the same scheduling mechanism. Every external assignment is logged
so the action sequence can be replayed against the same scenario.

Closure requests and durations are identical inputs across policies. A request
waits until its cell is unoccupied, then remains active for its specified duration
starting at actual activation. Actual activation can differ between policies and
is recorded. A closure never activates under a robot. Every tick rebuilds future
reservations against the active closure set. Imported closure requests are not
revealed through dispatch observation APIs (those APIs are a later section).

Wall-clock planning measurements are nondeterministic diagnostics and are kept
out of the deterministic tick trace. They never alter logical simulation time.
Current revision identity is package version 0.2.0; experiment manifests also
record SHA-256 hashes of all Python source files. Commit/model identities will
be included when the later experiment and publication sections are implemented.
