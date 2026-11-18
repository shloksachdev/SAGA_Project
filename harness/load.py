"""
Purpose: Open-loop load generator and throughput/latency profiler (§3.5, Task 4).
Phase: Phase 8
"""

import argparse
import concurrent.futures
import os
import random
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.contracts import (
    STATUS_COMPENSATED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    SagaEnvelope,
)
from harness.derive import derive_for_saga
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


def run_single_load_saga(
    path: str,
    workload: str,
    work_scale: float,
    inject_failure: bool,
    seed: int,
    timeout_sec: int = 60,
) -> Dict[str, Any]:
    """Runs a single saga execution within the load test."""
    runner = PATH_RUNNERS[path]
    saga_id = f"load-{path.lower()}-{uuid.uuid4().hex[:8]}"

    faults = {}
    if inject_failure:
        rng = random.Random(seed)
        step_choice = rng.choice(["Payment", "Inventory", "Notification"])
        if step_choice == "Payment":
            faults["Payment"] = {"forward": "fail", "errorName": "PaymentDeclined"}
        elif step_choice == "Inventory":
            faults["Inventory"] = {"forward": "fail", "errorName": "InventoryShortage"}
        else:
            faults["Notification"] = {"forward": "fail"}

    envelope = SagaEnvelope(
        sagaId=saga_id,
        path=path,
        workload=workload,
        runTag="load-test",
        workScale=work_scale,
        faults=faults,
    )

    t0 = time.time()
    try:
        runner(envelope, timeout_sec=timeout_sec)
        status = "COMPLETED" if not inject_failure else "COMPENSATED"
    except Exception as e:
        status = "FAILED"
    elapsed = time.time() - t0

    # Derive trace metrics
    try:
        derived = derive_for_saga(saga_id)
    except Exception:
        derived = {}

    return {
        "sagaId": saga_id,
        "path": path,
        "status": status,
        "elapsed": elapsed,
        "inject_failure": inject_failure,
        "happy_latency": derived.get("happy_latency"),
        "compensation_latency": derived.get("compensation_latency"),
    }


def run_load_test(
    path: str = "A",
    workload: str = "order",
    rate: float = 2.0,
    duration_sec: float = 10.0,
    failure_rate: float = 0.10,
    work_scale: float = 0.0,
    seed: int = 42,
    max_workers: int = 8,
) -> Dict[str, Any]:
    """
    Executes an open-loop load generator at a fixed rate (sagas/sec) over duration_sec.
    """
    random.seed(seed)
    total_sagas = max(1, int(rate * duration_sec))
    interval = 1.0 / rate if rate > 0 else 0.5

    print(f"\n[Load Generator] Starting open-loop load test: Path {path}, rate={rate} sagas/s, duration={duration_sec}s, total={total_sagas} sagas")

    results = []
    start_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for i in range(total_sagas):
            fail = (random.random() < failure_rate)
            s_seed = seed + i
            f = executor.submit(
                run_single_load_saga,
                path=path,
                workload=workload,
                work_scale=work_scale,
                inject_failure=fail,
                seed=s_seed,
            )
            futures.append(f)
            time.sleep(interval)

        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    total_time = time.time() - start_time
    completed_sagas = len(results)
    throughput = completed_sagas / total_time if total_time > 0 else 0.0

    happy_latencies = [
        r["happy_latency"] for r in results if r.get("happy_latency") is not None
    ]
    happy_latencies.sort()

    p50 = None
    p95 = None
    if happy_latencies:
        idx_50 = int(len(happy_latencies) * 0.50)
        idx_95 = min(len(happy_latencies) - 1, int(len(happy_latencies) * 0.95))
        p50 = happy_latencies[idx_50]
        p95 = happy_latencies[idx_95]

    metrics = {
        "path": path,
        "workload": workload,
        "total_dispatched": total_sagas,
        "completed_count": completed_sagas,
        "duration_sec": total_time,
        "throughput_sagas_per_sec": throughput,
        "happy_p50_ms": p50,
        "happy_p95_ms": p95,
    }

    print(f"[Load Generator] Path {path} Results: Throughput={throughput:.2f} sagas/s, p50={p50} ms, p95={p95} ms")
    return metrics


def main():
    parser = argparse.ArgumentParser(description="Open-loop load generator for distributed sagas")
    parser.add_argument("--path", default="A", choices=["A", "B", "C", "D"])
    parser.add_argument("--rate", type=float, default=2.0)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--workload", default="order")
    parser.add_argument("--failure-rate", type=float, default=0.10)
    parser.add_argument("--scale", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    run_load_test(
        path=args.path,
        workload=args.workload,
        rate=args.rate,
        duration_sec=args.duration,
        failure_rate=args.failure_rate,
        work_scale=args.scale,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
