# Visual console

```sh
./launch.sh
# If the default port is occupied:
./launch.sh --port 8766
```

Open the URL printed by the launcher. Setup creates an isolated Python environment,
installs web dependencies, installs frontend packages from the lockfile and builds
the production UI. Normal operation is offline and needs no training step. Python
and Node.js must already be installed. Ctrl-C stops the launched process; the
launcher never kills other services. requirements-web.lock records the full tested
Python environment, including optional research-plot and test dependencies.

## Runtime and controls

FastAPI owns the simulation clock; React/TypeScript renders server-sent snapshots.
The two runs share immutable inputs and advance together in integer ticks. UI
render speed cannot change logical outcomes. Dispatch choices may change actual
closure activation timing; exports retain it. The frozen model is unchanged.

Fleet console includes robot IDs, target rings, reserved paths, stations, optional
primary-run occupancy heatmap, live queue/status metrics and actual completion
history. Heat is cell occupancy count, not a learned risk estimate. Play, pause,
step, speed (1–30 ticks/sec), reset, seed and dispatcher controls operate on the
real simulator. Policy/scenario changes reset both runs. Comparing learned to
itself is allowed. Presets cover light demand, bottleneck, timed closure and a
previously evaluated held-out layout; that preset is no longer an untouched test.

Scenario editor holds a draft until Validate & apply. Clicking toggles walls;
stations and parking are protected. The same bounded schema validates JSON
imports. The console rejects disconnected jobs and limits scenarios to 25×25
cells, 300 jobs and 1,000 ticks. Applying structural edits resets both runs.
The headless simulator still supports explicit impossible-job accounting.

Experiments runs all three policies on the current scenario in a separate worker.
Progress, cancellation and actual result export are provided; cancellation retains
completed policy results. One scenario is not a statistical benchmark. Model
insights reads bundled metadata and saved held-out CSVs, shows model identities,
and preserves the measured mixed results rather than making live accuracy claims.

## Persistence and boundary

Session JSON under runs/console (or --storage) saves scenario, tick, policy, model
identity, speed and comparison setting. Restart reconstructs the deterministic
run and starts paused. Commands, every tenth live tick and normal shutdown save.
A changed model identity aborts restore. Experiment results persist separately;
unfinished tasks restore as interrupted. CPU timing can differ on replay; logical
traces and decisions are deterministic. Errors stop playback and preserve the
failing scenario instead of displaying invented progress.

Summary/trace exports include simulation revision, model identity, scenario hash,
policies, actual closures and recorded events. The server binds 127.0.0.1, rejects
unexpected Host/Origin values, requires bounded JSON mutations, serves only built
assets and exposes no arbitrary files or shell execution. No external fonts,
accounts or public hosting are needed. This is a local boundary, not public-server
authentication; do not expose this development service directly to the internet.

## Verification

42 tests pass with web dependencies installed: real API calls and inference,
commands, export identities, bad inputs, origin checks, independent snapshots,
restore, worker completion and cancellation. Production typecheck/build and a
relocated clean-copy build/test pass. Without web dependencies, two API tests skip;
the remaining headless checks still run.

Standalone Chrome launch was blocked here. The in-app browser verified playback,
step, comparison, model data, map editing/reset, background comparison cancellation
and completion, seed/reload persistence, learned dispatch and 780-pixel layout
without horizontal overflow. Actual screenshots are in docs/images. Export API
checks pass; a separate browser download check was interrupted by a browser-session
reset and is not claimed as verified. The standalone test script can run where
Chrome launch is available:

```sh
cd frontend
SWARMOPS_URL=http://127.0.0.1:8766 node scripts/browser-check.mjs
```

Results/browser.json distinguishes connected-browser checks from standalone launch
failure. No hosted CI or publication has been performed in this section.

References: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/),
[streaming](https://fastapi.tiangolo.com/advanced/stream-data/),
[React effects](https://react.dev/reference/react/useEffect).
