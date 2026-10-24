# Supervised duration prediction and evaluation

## Implementation and environment

Section 3 uses actual fitted numerical models. Scientific Python packages were
not installed on the Mac, and dependency installation failed because this
session could not reach the package index. To keep the work executable offline,
the project implements small ridge and regression-forest models in standard
Python. **These are not scikit-learn models.** The original NumPy/pandas/
scikit-learn/Matplotlib stack remains a possible later implementation, not a
dependency or a claim about the current build.

The forest trains bootstrapped regression trees using squared-error split
selection, a random subset of four features at each node, and bounded candidate
thresholds. Predictions average the trees. Ridge uses training-only centering
and scaling, unit L2 regularization on non-intercept coefficients, and a tiny
partial-pivot linear solver. Both predict the residual above static travel plus
service duration. Inference adds that residual back to the same static estimate.
Synthetic relationship, determinism, fitting, and save/load tests check these
implementations; they are small educational models without the breadth of
validation available in established scientific libraries.

## Data provenance and censoring

Collect assignments from distance, congestion, and a seeded exploratory policy.
Exploration randomizes pair rankings through a separate local RNG and cannot
change the order/closure stream. Training fleet size varies between four and six;
load varies between one order every eight and every two ticks. Layouts are seeded
shelf configurations with dimensions, shelf positions, and gaps that vary.

Each selected assignment logs policy, run ID, layout hash, scenario hash, seed,
feature timestamp, robot/job ID, feature values, status, and target. Target is
delivery completion tick minus assignment tick. Censored assignments have no
target and retain their observed duration lower bound. Summary tables retain
all released orders, backlog, impossible jobs, and censored assignments. Only
completed assignments enter ordinary regression fitting and prediction-error
metrics; this leaves selection and censoring bias. A model can underestimate
delays for hard or permanently blocked jobs.

Features are empty/loaded shortest-path distances, service time, occupied route
cells, nearby robots, queue length, fleet size, available robots, active jobs,
currently passable cell count, and the fraction of passable cells with degree
at most two. IDs, seeds, absolute time, future schedules, and completed durations
are not feature columns. A frozen observation supplies the current values before
assignment. Both heuristic and learned dispatch use the same candidate cap,
static-feasibility checks, greedy matching, aging, planner, and recovery rules.

## Splits, tuning and untouched evaluation

Full mode uses six entire training layouts, two validation layouts, two held-out
shelf layouts, and two held-out barrier layouts for stress testing. Geometry
hashes exclude labels and run IDs: renaming an identical map cannot make it
"held out." Distinct geometry hashes and run seeds are checked across all splits.
Full mode also excludes the layouts/seeds used for the earlier quick smoke test.
Full run seed ranges are 11000–11001 (train), 12000–12001 (validation),
13000–13019 (test), and 14000–14004 (stress). Whole trajectories stay together.

Evaluate exactly three fitted candidates on validation MAE: ridge, a 16-tree
depth-three forest with minimum leaf size 12, and a 24-tree depth-five forest
with minimum leaf size eight. The forest RNG seed is fixed at 17. Select the
lowest validation MAE and freeze it before generating test rollouts. Do not refit
on validation, inspect test metrics while tuning, or claim that minimizing MAE
optimizes dispatch. Validation-only permutation importance uses seed 23 and
measures predictive associations, not causal effects.

Final ordinary evaluation uses two held-out maps × two loads × 20 paired seeds
× three dispatchers: 240 runs. Stress evaluation changes topology, raises fleet
size to eight, and releases one order every tick: two barrier maps × five paired
seeds × three policies, or 30 additional runs. All run for 180 logical ticks.
Common input hashes/horizons/releases are asserted for every three-policy case.
Policy execution order rotates to reduce wall-time ordering bias.

Paired differences are learned minus each baseline. Reports separate layout,
demand, and ordinary/stress evaluation, and describe mean differences with sample
standard deviations. They do not claim statistical significance. Per-policy
completed MAE and bias, completed latency, completion fraction, backlog,
collision/stall counts, fallbacks, candidate time, and inference time are retained.
Feature-shift tables compare deployment means/range exceedances with collection
data, including censored assignments. These diagnostics do not correct shift.

## Safe persistence and fallback

Model JSON stores numerical tree nodes or regression weights and feature order.
A content hash identifies the model. The loader checks the hash, feature schema,
numeric finiteness, feature indices, tree depth/count, scaling, and size bounds.
It never imports code or loads pickle/joblib. SHA-256 checks integrity relative
to the metadata; it is not a signature or proof of a third party's authenticity.
The app has no user-uploaded model endpoint.

Learned matching calls the real fitted `predict` method once per candidate batch.
It falls back to the distance score for nonfinite/invalid predictions, invalid
features, fleets larger than eight, or combined static travel over 200 cells.
Every such candidate fallback is counted. The safety planner always remains
responsible for movement. A good duration estimate cannot make an impossible
fleet state solvable or establish performance on physical robots.

## Commands and artifacts

```sh
./train.sh --quick --output runs/ml-quick
./train.sh --output runs/ml-reproduction
./run.sh --policy learned --output runs/learned-demo
```

The bundled `models/demo` is a real trained model, so the learned demo requires
no manual training or package installation. Full reproduction generates a new
model independently; `--install-demo` explicitly replaces the bundled model.
Use a new/empty output directory. Training collection checkpoints after each
policy group, evaluation checkpoints after each policy run, and interruption
marks the manifest cancelled. There is no automatic resume yet.

Outputs include split/source manifests, collection samples and summaries,
selection scores, model/feature metadata, validation importance, per-assignment
prediction errors, feature-shift diagnostics, paired/full metrics, raw evaluation
logs, and five measured SVG charts. Optional PNG export needs locally installed
Playwright and Chrome; it never downloads them. Current execution restrictions
may prevent launching Chrome, in which case render-status.json records that
limitation. These chart exports are not screenshots of a finished web app.

Reference consulted for model persistence and compatibility considerations:
[scikit-learn model persistence](https://scikit-learn.org/stable/model_persistence.html).
The current JSON implementation uses no scikit-learn serializer or binary model.
