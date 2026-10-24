"""Render frozen recorded results with Matplotlib; never rerun or refit models."""
import csv
import argparse
import json
from pathlib import Path
from statistics import mean, stdev
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--results', type=Path, default=ROOT / 'results/ml-full')
OUT = parser.parse_args().results.resolve()
def read(name):
    with (OUT / name).open() as file:
        return list(csv.DictReader(file))
runs = [r for r in read("evaluation-runs.csv") if r["split"] == "test"]
predictions = [r for r in read("predictions.csv") if r["split"] == "test"]
pairs = [r for r in read("paired.csv") if r["split"] == "test"]
policies = ("distance", "congestion", "learned")
colors = ("#70a7ff", "#ffbd70", "#5ce8c5")
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.alpha": .18, "figure.facecolor": "#071319",
                     "axes.facecolor":"#0d1f28", "axes.edgecolor":"#45606b",
                     "grid.color":"#6b8793", "text.color":"#e7f0f1", "axes.labelcolor":"#a6bdc7",
                     "xtick.color":"#a6bdc7", "ytick.color":"#a6bdc7", "legend.frameon":False,
                     "axes.titleweight":"semibold", "axes.titlepad":16})
def figure(title, xlabel, ylabel):
    fig, ax = plt.subplots(figsize=(10, 5.6), layout="constrained")
    ax.set(title=title, xlabel=xlabel, ylabel=ylabel)
    return fig, ax
def save(fig, name):
    fig.savefig(OUT / "plots" / f"{name}.png", dpi=150)
    plt.close(fig)

fig, ax = figure("Held-out throughput by demand", "Demand (release interval)", "Completed orders / simulation tick")
for i, (policy, color) in enumerate(zip(policies, colors)):
    values = [mean(float(r["completed"]) / float(r["tick"]) for r in runs
                   if r["policy"] == policy and r["demand"] == load) for load in ("light", "heavy")]
    ax.bar(np.arange(2) + (i-1)*.24, values, width=.23, color=color, label=policy)
ax.set_xticks([0,1], ["Light (8 ticks)", "Heavy (2 ticks)"]); ax.legend(); save(fig, "throughput")

fig, ax = figure("Delivery latency with unfinished orders in the denominator", "Release-to-completion latency (ticks)", "Fraction of all released orders delivered")
for policy, color in zip(policies, colors):
    values = sorted(float(r["latency"]) for r in predictions if r["policy"] == policy and r["latency"])
    total = sum(int(r["released"]) for r in runs if r["policy"] == policy)
    ax.step([0]+values, [0]+[(i+1)/total for i in range(len(values))], where="post", color=color,
            label=f"{policy}: {len(values):,}/{total:,} delivered")
ax.set_ylim(0,1); ax.legend(); save(fig, "latency")

fig, ax = figure("Duration prediction error versus observed congestion", "Nearby robots at assignment", "Mean absolute prediction error (ticks)")
complete = [r for r in predictions if r["policy"] == "learned" and r["duration"]]
groups = sorted({int(r["nearby_robots"]) for r in complete})
for key, label, color in (("prediction", "learned", colors[2]), ("distance_prediction", "static duration", colors[0])):
    values = [mean(abs(float(r[key])-float(r["duration"])) for r in complete if int(r["nearby_robots"]) == g) for g in groups]
    ax.plot(groups, values, "o-", color=color, label=label)
counts = [sum(int(r["nearby_robots"]) == g for r in complete) for g in groups]
ax.set_xticks(groups,[f"{g}\n(n={n})" for g,n in zip(groups,counts)]); ax.legend(); save(fig, "prediction-error")

fig, ax = figure("Paired held-out completion differences · mean ± sample SD", "Learned minus baseline completed orders (SD, not CI)", "Layout / demand / baseline")
groups = sorted({(p["layout_id"], p["demand"], p["baseline"]) for p in pairs})
for index, (layout, load, baseline) in enumerate(groups):
    values = [float(p["delta_completed"]) for p in pairs if (p["layout_id"],p["demand"],p["baseline"]) == (layout,load,baseline)]
    ax.errorbar(mean(values), index, xerr=stdev(values), fmt="o", capsize=4,
                color=colors[policies.index(baseline)])
ax.axvline(0,color="#64748b",ls="--",lw=1)
ax.set_yticks(range(len(groups)),[f"{layout[:6]} / {load} / {baseline} (n={sum((p['layout_id'],p['demand'],p['baseline'])==(layout,load,baseline) for p in pairs)})" for layout,load,baseline in groups]); save(fig, "paired-comparison")

fig, ax = figure("Assigned-robot waiting · includes service, pauses and blocked movement", "Demand", "Mean waiting ticks per run")
for i, (policy, color) in enumerate(zip(policies, colors)):
    values = [mean(float(r["waiting_ticks"]) for r in runs if r["policy"] == policy and r["demand"] == load) for load in ("light", "heavy")]
    ax.bar(np.arange(2)+(i-1)*.24,values,width=.23,color=color,label=policy)
ax.set_xticks([0,1],["Light","Heavy"]); ax.legend(); save(fig, "waiting")
(OUT / "plots" / "matplotlib-render.json").write_text(json.dumps({"passed":True,"renderer":"matplotlib",
    "version":matplotlib.__version__,"charts":5,"source":"existing frozen CSV results; no retraining"},indent=2)+"\n")
print("Rendered five measured PNG charts without changing the frozen model.")
