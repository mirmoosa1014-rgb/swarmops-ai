"""Deterministic SVG charts from measured results; optional browser PNG export.

Uses no network resources. PNG export requires an installed Playwright/Chrome.
"""
from html import escape
import json
from pathlib import Path
from statistics import mean, stdev
import subprocess

COLORS = {"distance": "#2563eb", "congestion": "#d97706", "learned": "#15803d"}


def text(x, y, value, size=13, **attrs):
    extra = " ".join(f'{k.replace("_", "-")}="{escape(str(v))}"' for k, v in attrs.items())
    return f'<text x="{x}" y="{y}" font-size="{size}" {extra}>{escape(str(value))}</text>'


def frame(title, subtitle, body, footer="Held-out simulation data; see report.md for limitations."):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="650" viewBox="0 0 1100 650">'
            '<rect width="1100" height="650" fill="#ffffff"/>'
            '<g font-family="Arial, sans-serif" fill="#172033">' + text(32, 40, title, 24)
            + text(32, 69, subtitle, 14) + body + text(32, 625, footer, 13) + '</g></svg>')


def bars(title, subtitle, series, unit):
    maximum = max((value for _, value, _ in series), default=1) or 1
    body = ""
    spacing = min(70, 470 / max(1, len(series)))
    for i, (label, value, color) in enumerate(series):
        y = 115 + i * spacing
        body += text(32, y + 20, label)
        body += f'<rect x="300" y="{y}" width="{value / maximum * 640}" height="28" fill="{color}"/>'
        body += text(945, y + 20, f"{value:.3f}")
    body += text(300, 580, f"Bar length: {unit}", 14)
    return frame(title, subtitle, body)


def generate_plots(output, runs, predictions, paired):
    plots = output / "plots"
    plots.mkdir(exist_ok=True)
    test_runs = [r for r in runs if r["split"] == "test"]
    series = []
    for demand in ("light", "heavy"):
        for policy, color in COLORS.items():
            group = [r for r in test_runs if r["demand"] == demand and r["policy"] == policy]
            series.append((f"{demand} / {policy} (n={len(group)})",
                           mean(r["completed"] / r["tick"] for r in group), color))
    (plots / "throughput.svg").write_text(bars("Throughput versus demand", "Average jobs completed per simulation tick", series, "jobs / tick"))
    # ECDF denominator includes all released jobs, so unfinished work remains visible.
    body = '<path d="M90 110V540H1020" fill="none" stroke="#334155"/>'
    for fraction in (0, .25, .5, .75, 1):
        y = 540 - fraction * 400
        body += f'<path d="M90 {y}H1020" stroke="#e2e8f0"/>' + text(35, y + 5, f"{fraction:.0%}")
    maximum = max((p["latency"] for p in predictions if p["split"] == "test" and p["latency"] is not None), default=1)
    for index, (policy, color) in enumerate(COLORS.items()):
        group = [r for r in test_runs if r["policy"] == policy]
        released = sum(r["released"] for r in group)
        values = sorted(p["latency"] for p in predictions if p["split"] == "test" and p["policy"] == policy and p["latency"] is not None)
        points = [(90, 540)]
        for i, value in enumerate(values):
            x = 90 + value / maximum * 930
            points.extend(((x, 540 - i / released * 400), (x, 540 - (i + 1) / released * 400)))
        body += f'<polyline points="{" ".join(f"{x:.2f},{y:.2f}" for x,y in points)}" fill="none" stroke="{color}" stroke-width="2"/>'
        body += text(110 + index * 310, 103, f"{policy}: {len(values)}/{released} delivered", 13, fill=color)
    for i in range(6):
        body += text(90 + i / 5 * 930, 565, f"{i / 5 * maximum:.0f}", text_anchor="middle")
    body += text(400, 593, "Release-to-completion latency (ticks)", 15)
    (plots / "latency.svg").write_text(frame("Delivery latency with completion fractions", "Curve height is delivered fraction of all released orders, including unfinished work in the denominator.", body))
    series = []
    for bucket in range(5):
        group = [p for p in predictions if p["split"] == "test" and p["policy"] == "learned"
                 and not p["censored"] and min(4, p["nearby_robots"]) == bucket]
        if group:
            for key, label, color in (("prediction", "ML", COLORS["learned"]),
                                      ("distance_prediction", "distance", COLORS["distance"])):
                series.append((f"nearby {bucket}{'+' if bucket == 4 else ''} / {label} (n={len(group)})",
                               mean(abs(p[key] - p["duration"]) for p in group), color))
    (plots / "prediction-error.svg").write_text(bars("Prediction error versus current congestion", "MAE on completed assignments from the learned policy's held-out rollouts", series, "absolute duration error (ticks)"))
    groups = sorted({(p["layout_id"], p["demand"], p["baseline"]) for p in paired if p["split"] == "test"})
    stats = []
    for layout, demand, baseline in groups:
        values = [p["delta_completed"] for p in paired if p["split"] == "test" and
                  (p["layout_id"], p["demand"], p["baseline"]) == (layout, demand, baseline)]
        stats.append((f"{layout[:6]} / {demand} / vs {baseline}", mean(values), stdev(values) if len(values) > 1 else 0, len(values)))
    bound = max((abs(m) + sd for _, m, sd, _ in stats), default=1) or 1
    body = '<path d="M690 100V565" stroke="#64748b" stroke-dasharray="4 4"/>'
    for i, (label, average, sd, n) in enumerate(stats):
        y = 125 + i * 53
        center, half = 690 + average / bound * 245, sd / bound * 245
        body += text(30, y + 5, f"{label} (n={n})", 12)
        body += f'<path d="M{center-half} {y}H{center+half}" stroke="#15803d" stroke-width="3"/>'
        body += f'<circle cx="{center}" cy="{y}" r="5" fill="#15803d"/>'
        body += text(960, y + 5, f"{average:+.2f} ± {sd:.2f}", 12)
    body += text(445, 590, "← fewer completions     0     more completions →", 14)
    (plots / "paired-comparison.svg").write_text(frame("Paired held-out completion differences", "Learned minus baseline: mean ± sample SD across seeds; bars are not confidence intervals.", body))
    series = []
    for demand in ("light", "heavy"):
        for policy, color in COLORS.items():
            group = [r for r in test_runs if r["demand"] == demand and r["policy"] == policy]
            series.append((f"{demand} / {policy}", mean(r["waiting_ticks"] for r in group), color))
    (plots / "waiting.svg").write_text(bars("Robot waiting-time comparison", "Mean assigned-robot waiting ticks per run; includes loading, unloading, pauses and blocked movement", series, "waiting ticks / run"))
    # A standard browser rasterizes exact chart SVGs; this does not simulate an app screenshot.
    script = Path(__file__).resolve().parents[2] / "scripts" / "render-plots.cjs"
    try:
        result = subprocess.run(["node", str(script), str(plots.resolve())], capture_output=True, text=True, timeout=60)
        status = {"png_exported": result.returncode == 0, "details": (result.stdout + result.stderr)[-2000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        status = {"png_exported": False, "details": str(exc)}
    (plots / "render-status.json").write_text(json.dumps(status, indent=2) + "\n")
