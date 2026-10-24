# Bundled model card — v0.3.0

Model identity: `0df091ba42337d4a4285e5ddf8c322f2bb9e77565bc7fe689f66cf3e90829251`.
Artifact: `models/demo/model.json`, with `metadata.json` describing its provenance.

## Purpose and implementation

Predict assignment-to-delivery duration in logical ticks for idle robot/job pairs
in this project's simulation. Matching uses that prediction with the common
aging and greedy assignment rules. The shared movement planner enforces safety.

The model is a project-implemented bootstrapped regression forest: 24 trees,
maximum depth five, minimum leaf size eight, four randomly selected features
per split, seven bounded candidate split positions, RNG seed 17. It learns the
residual over static travel plus service duration. Ridge and a smaller forest
were also fitted; selection used validation MAE only.

These models use standard Python, not scikit-learn. Scientific package downloads
were blocked in the development session. The custom implementation is tested
but lacks the breadth of validation of an established scientific library.

## Data and selection

Training: 2,068 completed assignments from 72 episodes on six training layouts,
with 252 additional censored assignments logged but excluded from regression
fitting. Collection mixed distance, congestion and seeded exploratory dispatch,
four/six robots, and two demand levels. Validation: 721 completed assignments
from 24 episodes on two other layouts. Layout geometry and run seeds are disjoint
across training, validation, test and stress splits. Full splits are also disjoint
from the earlier quick smoke test.

Eleven current-state features describe travel, service, current congestion,
queue/fleet state and topology. IDs, seeds, absolute timestamps, future schedules
and target durations are not model features. The model receives only candidates
constructed from the shared immutable observation boundary.

Validation MAE: selected forest 2.034 ticks; static duration estimate 1.840 ticks.
The forest won among the fitted candidates but did not beat the static prediction
baseline. Final test results were not used to change the fitted model or settings.

## Measured behavior

Ordinary held-out evaluation: two new shelf layouts, two loads, 20 paired seeds
per layout/load, four robots, 180 ticks. Each policy saw 4,520 released jobs over
80 runs:

| Policy | Completed jobs | Remaining backlog |
|---|---:|---:|
| Distance | 2,156 | 2,364 |
| Congestion | 2,241 | 2,279 |
| Learned | 2,192 | 2,328 |

The aggregate improvement over distance was small and variable. No statistical
significance is claimed. On completed learned-policy assignments, model MAE was
2.273 ticks versus 2.108 for the static estimate; model bias was -0.803 ticks.

Stress evaluation changed to barrier layouts, eight robots and one release per
tick, with five paired seeds on each of two layouts. Of 1,800 released jobs per
policy, learned completed 351, distance 359 and congestion 460. On completed
learned-policy assignments, learned MAE was 4.071 ticks versus 4.459 for static
duration. Prediction improvement here did not improve dispatch throughput.

All 270 final evaluation runs recorded zero vertex or opposite-edge violations.
This observed result is not a proof for arbitrary scenarios. No inference
fallbacks occurred in final evaluation; unit tests exercise fallback behavior.

## Limitations and safeguards

- Completed-only fitting leaves censoring and collection-policy selection bias.
- Data records selected assignments, not counterfactual outcomes for every pair.
- Deployment changes the feature distribution; stress generalization is poor.
- Twenty seeds do not turn two held-out layouts into broad real-world evidence.
- The planner is incomplete, horizons finite, and robot physics simplified.
- No physical warehouse validation, causal feature effects or consistent speedup.

Inference falls back to distance for invalid/nonfinite predictions or features,
fleets above eight, or combined static travel above 200 cells. Numerical JSON
stores model state; loading checks feature order, bounded nodes and values, size,
and a content hash. No pickle/joblib or executable model file is loaded. A hash
checks integrity relative to metadata, not third-party authenticity.

## Reproduction and evidence

`./run.sh --policy learned` uses the real bundled model without manual training.
`./train.sh --output runs/ml-reproduction` independently repeats collection,
training, frozen evaluation and chart generation. Full pipeline time was about
140 seconds on the development machine, using Python 3.14.3.

See `results/ml-full` for source/split/data hashes, selection scores, predictions,
feature shift, validation importance, paired differences, run metrics and report.
Five SVG charts were generated. PNG export was blocked by the unavailable browser
runtime; no web UI check or app screenshot is claimed in section 3.

Any tuning after viewing these results requires fresh final test layouts and
seeds. Preserve the current model identity and mixed results as a versioned
experiment instead of silently replacing its evaluation.
