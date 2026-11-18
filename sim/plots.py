"""
Purpose: Publication-quality plotting for SimPy simulation sweep results (SPEC §4 Phase 9).
Phase: Phase 9
"""

import os
import sys
from typing import Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


# Okabe-Ito colorblind-safe palette (matching paper/style.py)
COLORS = {
    "blue": "#0072B2",
    "orange": "#E69F00",
    "green": "#009E73",
    "red": "#D55E00",
    "purple": "#CC79A7",
    "gray": "#7F7F7F",
}


def plot_all(results_dir: str, out_dir: Optional[str] = None):
    """Generates all simulation plots from CSV files in results_dir."""
    out_dir = out_dir or os.path.join(results_dir, "plots")
    os.makedirs(out_dir, exist_ok=True)

    plot_election_overhead(results_dir, out_dir)
    plot_makespan_reduction(results_dir, out_dir)
    plot_re_elections(results_dir, out_dir)
    plot_contention_scaling(results_dir, out_dir)


def plot_election_overhead(results_dir: str, out_dir: str):
    csv_path = os.path.join(results_dir, "election_sweep.csv")
    if not os.path.exists(csv_path):
        return
    df = pd.read_csv(csv_path)

    fig, ax = plt.subplots(figsize=(6.5, 4.2), dpi=300)
    for dist, col in zip(["constant", "lognormal", "heavy_tailed"], [COLORS["blue"], COLORS["orange"], COLORS["green"]]):
        sub = df[df["distribution"] == dist]
        if sub.empty:
            continue
        agg = sub.groupby("participants")["election_latency_ms"].agg(["median", "min", "max"]).reset_index()
        label_map = {"constant": "Constant (15 ms)", "lognormal": "Lognormal (med=15 ms)", "heavy_tailed": "Heavy-Tailed (Pareto)"}
        ax.plot(agg["participants"], agg["median"], marker="o", color=col, label=label_map.get(dist, dist), linewidth=2)
        ax.fill_between(agg["participants"], agg["min"], agg["max"], color=col, alpha=0.15)

    ax.set_title("DynamoDB Lease Election Overhead vs Participant Count", fontsize=11, fontweight="bold")
    ax.set_xlabel("Number of Participating Services (N)", fontsize=10)
    ax.set_ylabel("Election Latency (ms)", fontsize=10)
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend(frameon=True, fontsize=9)
    plt.tight_layout()

    fig.savefig(os.path.join(out_dir, "election_overhead.png"), dpi=300)
    fig.savefig(os.path.join(out_dir, "election_overhead.pdf"))
    plt.close(fig)


def plot_makespan_reduction(results_dir: str, out_dir: str):
    csv_path = os.path.join(results_dir, "makespan_sweep.csv")
    if not os.path.exists(csv_path):
        return
    df = pd.read_csv(csv_path)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.2), dpi=300)
    
    # Filter width sweep
    w_df = df[df["depth"] == 1].groupby(["width", "comp_mode"])["makespan_ms"].median().unstack().reset_index()
    if "parallel" in w_df and "lifo" in w_df:
        ax1.plot(w_df["width"], w_df["lifo"], marker="s", color=COLORS["red"], label="LIFO Sequential", linewidth=2)
        ax1.plot(w_df["width"], w_df["parallel"], marker="o", color=COLORS["blue"], label="Dynamic DAG Parallel", linewidth=2)
        ax1.set_title("Compensation Makespan vs DAG Width", fontsize=11, fontweight="bold")
        ax1.set_xlabel("DAG Concurrency Width (k)", fontsize=10)
        ax1.set_ylabel("Makespan (ms)", fontsize=10)
        ax1.grid(True, linestyle="--", alpha=0.5)
        ax1.legend(frameon=True, fontsize=9)

        # Reduction %
        reduction = (w_df["lifo"] - w_df["parallel"]) / w_df["lifo"] * 100.0
        ax2.plot(w_df["width"], reduction, marker="^", color=COLORS["green"], linewidth=2)
        ax2.axhline(25.0, color=COLORS["gray"], linestyle=":", label="Phase 7B Threshold (25%)")
        ax2.set_title("Makespan Reduction vs DAG Width", fontsize=11, fontweight="bold")
        ax2.set_xlabel("DAG Concurrency Width (k)", fontsize=10)
        ax2.set_ylabel("Reduction (%)", fontsize=10)
        ax2.grid(True, linestyle="--", alpha=0.5)
        ax2.legend(frameon=True, fontsize=9)

    plt.tight_layout()
    fig.savefig(os.path.join(out_dir, "makespan_reduction.png"), dpi=300)
    fig.savefig(os.path.join(out_dir, "makespan_reduction.pdf"))
    plt.close(fig)


def plot_re_elections(results_dir: str, out_dir: str):
    csv_path = os.path.join(results_dir, "crash_sweep.csv")
    if not os.path.exists(csv_path):
        return
    df = pd.read_csv(csv_path)

    fig, ax = plt.subplots(figsize=(6.5, 4.2), dpi=300)
    agg = df.groupby("crash_p")["re_elections"].agg(["mean", "median"]).reset_index()
    ax.plot(agg["crash_p"], agg["mean"], marker="D", color=COLORS["purple"], label="Mean Re-Elections", linewidth=2)
    ax.set_title("Lease Re-Elections vs Leader Crash Probability", fontsize=11, fontweight="bold")
    ax.set_xlabel("Leader Crash Probability (p)", fontsize=10)
    ax.set_ylabel("Average Re-Election Count", fontsize=10)
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend(frameon=True, fontsize=9)
    plt.tight_layout()

    fig.savefig(os.path.join(out_dir, "re_elections.png"), dpi=300)
    fig.savefig(os.path.join(out_dir, "re_elections.pdf"))
    plt.close(fig)


def plot_contention_scaling(results_dir: str, out_dir: str):
    csv_path = os.path.join(results_dir, "contention_sweep.csv")
    if not os.path.exists(csv_path):
        return
    df = pd.read_csv(csv_path)

    fig, ax = plt.subplots(figsize=(6.5, 4.2), dpi=300)
    ax.plot(df["lambda_rate"], df["mean_makespan_ms"], marker="o", color=COLORS["blue"], label="Mean Makespan", linewidth=2)
    ax.plot(df["lambda_rate"], df["p95_makespan_ms"], marker="^", color=COLORS["red"], label="p95 Makespan", linewidth=2)
    ax.set_title("Compensation Latency vs Sagas Arrival Rate (λ)", fontsize=11, fontweight="bold")
    ax.set_xlabel("Arrival Rate λ (sagas/s)", fontsize=10)
    ax.set_ylabel("Makespan (ms)", fontsize=10)
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend(frameon=True, fontsize=9)
    plt.tight_layout()

    fig.savefig(os.path.join(out_dir, "contention_scaling.png"), dpi=300)
    fig.savefig(os.path.join(out_dir, "contention_scaling.pdf"))
    plt.close(fig)


if __name__ == "__main__":
    import sys
    res_dir = sys.argv[1] if len(sys.argv) > 1 else "results/sim"
    plot_all(res_dir)
    print(f"[Success] Simulation plots saved in {res_dir}/plots")
