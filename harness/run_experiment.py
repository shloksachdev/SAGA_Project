"""
Purpose: Main experiment runner and data collector (§4 Phase 8 Task 1).
Phase: Phase 8
"""

import argparse
import csv
import json
import os
import random
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.contracts import SagaEnvelope
from harness.consistency import check_consistency
from harness.cost import calculate_run_cost, load_pricing
from harness.derive import derive_for_saga
from harness.manifest import append_to_experiment_log, create_manifest, write_manifest
from paths.a.run import start_saga as start_saga_a
from paths.b.run import start_saga as start_saga_b
from paths.c.run import start_saga as start_saga_c
from paths.d.run import start_saga as start_saga_d

PATH_RUNNERS = {
    "A": start_saga_a,
    "B": start_saga_b,
    "C": start_saga_c,
    "D": start_saga_d,
}


def load_config(config_path: str) -> Dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_execution_plan(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Builds the complete randomized, interleaved execution plan across paths.
    """
    paths = config.get("paths", ["A", "B", "C", "D"])
    workloads = config.get("workloads", ["order"])
    work_scale = float(config.get("workScale", 1.0))
    scenarios = config.get("scenarios", [])
    default_reps = int(config.get("repetitions", 2))
    warmup_count = int(config.get("warmupCount", 0))
    seed = int(config.get("seed", 42))

    plan: List[Dict[str, Any]] = []

    for wl in workloads:
        # 1. Warm-up runs per path
        for p in paths:
            for w_idx in range(warmup_count):
                plan.append(
                    {
                        "path": p,
                        "workload": wl,
                        "workScale": work_scale,
                        "scenario": "warmup",
                        "faults": {},
                        "leaderFault": None,
                        "warmup": True,
                    }
                )

        # 2. Measurement scenarios
        for scen in scenarios:
            scen_name = scen.get("name", "unnamed")
            scen_paths = scen.get("paths", paths)
            scen_workloads = scen.get("workloads")
            if scen_workloads and wl not in scen_workloads:
                continue
            scen_count = scen.get("count", default_reps)
            faults = scen.get("faults", {})
            leader_fault = scen.get("leaderFault", None)
            comp_mode = scen.get("compMode", "parallel")

            for p in scen_paths:
                if p not in paths:
                    continue
                for rep in range(scen_count):
                    plan.append(
                        {
                            "path": p,
                            "workload": wl,
                            "workScale": work_scale,
                            "scenario": scen_name,
                            "faults": faults,
                            "leaderFault": leader_fault,
                            "compMode": comp_mode,
                            "warmup": False,
                        }
                    )

    # Interleave runs across paths in seeded randomized order (SPEC §4 Task 1)
    rng = random.Random(seed)
    rng.shuffle(plan)
    return plan


def run_single_experiment(
    item: Dict[str, Any],
    run_tag: str,
    pricing: Dict[str, Any],
    timeout_sec: int = 60,
) -> Dict[str, Any]:
    path = item["path"]
    workload = item["workload"]
    work_scale = item["workScale"]
    scenario = item["scenario"]
    faults = item["faults"]
    leader_fault = item.get("leaderFault")
    comp_mode = item.get("compMode", "parallel")
    is_warmup = item.get("warmup", False)

    saga_id = f"exp-{run_tag[:6]}-{path.lower()}-{uuid.uuid4().hex[:8]}"
    runner = PATH_RUNNERS[path]

    envelope = SagaEnvelope(
        sagaId=saga_id,
        path=path,
        workload=workload,
        runTag=run_tag,
        workScale=work_scale,
        faults=faults,
        leaderFault=leader_fault,
        compMode=comp_mode,
    )

    t0 = time.time()
    timed_out = False
    exec_error = None

    try:
        runner(envelope, timeout_sec=timeout_sec)
    except Exception as e:
        exec_error = str(e)
        if "timeout" in exec_error.lower() or "timed out" in exec_error.lower():
            timed_out = True

    duration = time.time() - t0

    # Derive metrics from SagaTrace
    derived = derive_for_saga(saga_id)
    # Right-censoring at 60 s for timed-out or incomplete runs (SPEC §4 Phase 10 Task 4)
    if timed_out and derived.get("compensation_latency") is None:
        derived["compensation_latency"] = 60000.0
        derived["scheduling_makespan"] = 60000.0
        derived["censored"] = True
    else:
        derived["censored"] = False

    # Check consistency
    is_consistent, violations = check_consistency(saga_id)
    # Calculate costs
    cost_info = calculate_run_cost(derived, pricing=pricing)

    record = {
        "sagaId": saga_id,
        "runTag": run_tag,
        "path": path,
        "workload": workload,
        "scenario": scenario,
        "compMode": comp_mode,
        "warmup": is_warmup,
        "timedOut": timed_out,
        "error": exec_error,
        "consistent": is_consistent,
        "consistencyViolations": violations,
        "wallClockDuration": duration,
        "metrics": derived,
        "cost": cost_info,
    }
    return record


def run_experiment(
    config_path: str,
    run_tag: Optional[str] = None,
    output_dir: str = "results",
) -> str:
    config = load_config(config_path)
    tag = run_tag or f"{config.get('name', 'experiment')}-{int(time.time())}"
    pricing = load_pricing()

    raw_dir = os.path.join(PROJECT_ROOT, output_dir, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    jsonl_path = os.path.join(raw_dir, f"{tag}.jsonl")
    csv_path = os.path.join(PROJECT_ROOT, output_dir, "summary.csv")

    plan = build_execution_plan(config)
    print(f"\n[Experiment] Loaded config '{config_path}': {len(plan)} total runs planned under runTag '{tag}'")
    print(f"[Experiment] Output JSONL: {jsonl_path}")

    t0_run = time.time()
    all_records = []
    with open(jsonl_path, "w", encoding="utf-8") as f_jsonl:
        for idx, item in enumerate(plan):
            print(f"  [{idx+1}/{len(plan)}] Running Path {item['path']} ({item['workload']}, {item['scenario']}, warmup={item['warmup']})...")
            record = run_single_experiment(item, run_tag=tag, pricing=pricing)
            all_records.append(record)
            f_jsonl.write(json.dumps(record) + "\n")
            f_jsonl.flush()

    t1_run = time.time()

    # Generate summary CSV
    _write_summary_csv(all_records, csv_path)
    print(f"[Experiment] Completed {len(all_records)} runs. Summary written to {csv_path}")

    # Generate and write provenance manifest (SPEC §4 Phase 10 Task 2)
    manifest_path = os.path.join(raw_dir, f"{tag}.manifest.json")
    manifest = create_manifest(
        run_tag=tag,
        config_path=config_path,
        start_time=t0_run,
        end_time=t1_run,
        records=all_records,
        seed=int(config.get("seed", 42)),
    )
    write_manifest(manifest, manifest_path)
    append_to_experiment_log(manifest)
    print(f"[Experiment] Provenance manifest written to {manifest_path}")
    print(f"[Experiment] Provenance audit entry appended to docs/EXPERIMENT_LOG.md")

    return jsonl_path


def _write_summary_csv(records: List[Dict[str, Any]], csv_path: str) -> None:
    from collections import defaultdict
    groups = defaultdict(list)
    for r in records:
        if r.get("warmup"):
            continue
        key = (r["path"], r["workload"], r["scenario"])
        groups[key].append(r)

    rows = []
    for (path, workload, scenario), group_runs in sorted(groups.items()):
        n = len(group_runs)
        timeouts = sum(1 for r in group_runs if r.get("timedOut"))
        consistents = sum(1 for r in group_runs if r.get("consistent"))

        happy_lats = [r["metrics"].get("happy_latency") for r in group_runs if r["metrics"].get("happy_latency") is not None]
        comp_lats = [r["metrics"].get("compensation_latency") for r in group_runs if r["metrics"].get("compensation_latency") is not None]
        makespans = [r["metrics"].get("scheduling_makespan") for r in group_runs if r["metrics"].get("scheduling_makespan") is not None]
        costs = [r["cost"].get("total_cost", 0.0) for r in group_runs]

        median_happy = sorted(happy_lats)[len(happy_lats) // 2] if happy_lats else ""
        median_comp = sorted(comp_lats)[len(comp_lats) // 2] if comp_lats else ""
        median_makespan = sorted(makespans)[len(makespans) // 2] if makespans else ""
        avg_cost = sum(costs) / max(1, n)
        cost_1k = avg_cost * 1000.0

        rows.append(
            {
                "path": path,
                "workload": workload,
                "scenario": scenario,
                "runs": n,
                "consistent_pct": (consistents / n) * 100.0 if n > 0 else 0.0,
                "timeouts": timeouts,
                "median_happy_latency_ms": median_happy,
                "median_compensation_latency_ms": median_comp,
                "median_makespan_ms": median_makespan,
                "avg_cost_usd": f"{avg_cost:.6f}",
                "cost_per_1k_usd": f"{cost_1k:.4f}",
            }
        )

    fieldnames = [
        "path",
        "workload",
        "scenario",
        "runs",
        "consistent_pct",
        "timeouts",
        "median_happy_latency_ms",
        "median_compensation_latency_ms",
        "median_makespan_ms",
        "avg_cost_usd",
        "cost_per_1k_usd",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Run saga experiments from config JSON")
    parser.add_argument("--config", required=True, help="Path to config JSON")
    parser.add_argument("--runTag", default=None, help="Custom runTag label")
    parser.add_argument("--output-dir", default="results", help="Base output directory")
    args = parser.parse_args()

    run_experiment(args.config, run_tag=args.runTag, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
