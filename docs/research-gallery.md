# Research gallery

All graphs come from committed evaluation CSVs. Rendering does not refit the model.
Sources: scripts/render-scientific-plots.py and scripts/render-research-overview.py.

![Policy outcomes](images/research-overview.png)
![Throughput](../results/ml-full/plots/throughput.png)
![Latency](../results/ml-full/plots/latency.png)

The latency denominator includes all released orders, so curves do not reach
100% when jobs remain unfinished at the horizon.

![Prediction errors](../results/ml-full/plots/prediction-error.png)

Errors use completed learned-policy assignments. Bucket counts are shown;
difficult censored jobs may be absent from this observed sample.

![Paired differences](../results/ml-full/plots/paired-comparison.png)

Zero means equal completed counts. Bars are sample SD across paired seeds,
not confidence intervals or proof of statistical significance.

![Waiting ticks](../results/ml-full/plots/waiting.png)

Waiting includes service, pauses and blocked movement while assigned, and
excludes idle parking time.

![Actual console](images/console.png)
![Actual model panel](images/model.png)
![Actual experiment](images/experiment.png)
![Recorded movement](images/simulation.gif)

The GIF renders exported positions rather than recording the browser. No stock
or generated warehouse imagery is used as evidence of a working system.
