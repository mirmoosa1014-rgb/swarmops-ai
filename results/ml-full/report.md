# Real ML evaluation

Mode: full. Model: `0df091ba42337d4a4285e5ddf8c322f2bb9e77565bc7fe689f66cf3e90829251`.
Selected: forest; 2068 training completions; 252 censored training assignments.
Full pipeline wall time: 139.49 seconds.

| Split | Policy | Runs | Completed / released | Mean completion fraction | Mean completed latency | Fallbacks |
|---|---|---:|---:|---:|---:|---:|
| test | distance | 80 | 2156 / 4520 | 0.622 | 32.02 | 0 |
| test | congestion | 80 | 2241 / 4520 | 0.634 | 30.84 | 0 |
| test | learned | 80 | 2192 / 4520 | 0.627 | 31.97 | 0 |
| ood | distance | 10 | 359 / 1800 | 0.199 | 36.30 | 0 |
| ood | congestion | 10 | 460 / 1800 | 0.256 | 43.99 | 0 |
| ood | learned | 10 | 351 / 1800 | 0.195 | 36.87 | 0 |

Paired completion differences (learned minus baseline), by layout and demand:

| Split | Layout | Demand | Baseline | Pairs | Mean delta ± sample SD |
|---|---|---|---|---:|---:|
| ood | 6e500a91bb | stress | congestion | 5 | -20.40 ± 18.88 |
| ood | 6e500a91bb | stress | distance | 5 | -3.60 ± 9.18 |
| ood | 93b6fac22d | stress | congestion | 5 | -1.40 ± 15.99 |
| ood | 93b6fac22d | stress | distance | 5 | 2.00 ± 11.55 |
| test | 60740af8c9 | heavy | congestion | 20 | -0.85 ± 11.55 |
| test | 60740af8c9 | heavy | distance | 20 | 0.10 ± 11.19 |
| test | 60740af8c9 | light | congestion | 20 | 0.00 ± 0.32 |
| test | 60740af8c9 | light | distance | 20 | 0.00 ± 0.00 |
| test | a121975ad6 | heavy | congestion | 20 | -1.65 ± 8.29 |
| test | a121975ad6 | heavy | distance | 20 | 1.70 ± 8.57 |
| test | a121975ad6 | light | congestion | 20 | 0.05 ± 0.39 |
| test | a121975ad6 | light | distance | 20 | 0.00 ± 0.00 |

SD is descriptive, not a confidence interval. Completed latency excludes unfinished
jobs and must be read with completion fractions and backlog. Waiting includes service.
Collision violations: 0.

## Limitations

Models are small project implementations of ridge regression and a bootstrapped randomized
regression forest, not scikit-learn. Package installation was blocked in the development
session. Training, inference, and persistence use only standard Python and bounded JSON.
Only completed assignments supply regression labels: censoring and collection-policy
selection bias remain. Deployment changes the state distribution. Duration prediction
is not counterfactual policy optimization; better MAE need not improve fleet throughput.
Final results were not used to tune models. Any later tuning requires a fresh final split.
Validation permutation importance is predictive, not causal. No physical validation.
