"""
Purpose: Phase 7B acceptance tests for synthetic wide-fan workloads (wide-2, wide-4, wide-6).
Phase: Phase 7B
"""

import time
import uuid
import pytest
from boto3.dynamodb.conditions import Key

from common.aws import get_table
from common.contracts import (
    COMP_COMPLETED,
    COMP_NEEDED_PUBLISHED,
    COMP_STARTED,
    LEASE_ACQUIRED,
    SAGA_COMPENSATED,
    SAGA_COMPLETED,
    STATUS_COMPENSATED,
    STATUS_COMPLETED,
    SagaEnvelope,
)
from paths.d.run import start_saga as start_saga_d


def get_trace_events(saga_id: str):
    trace_table = get_table("SagaTrace")
    resp = trace_table.query(KeyConditionExpression=Key("sagaId").eq(saga_id))
    return resp.get("Items", [])


def get_run_item(saga_id: str):
    runs_table = get_table("SagaRuns")
    resp = runs_table.get_item(Key={"sagaId": saga_id})
    return resp.get("Item")


def get_step_item(saga_id: str, step_name: str):
    steps_table = get_table("SagaSteps")
    resp = steps_table.get_item(Key={"sagaId": saga_id, "step": step_name})
    return resp.get("Item")


def test_wide_fan_happy_path():
    """Wide-4 forward execution runs all 5 steps (Order + Step1..4) to completion."""
    saga_id = f"saga-7b-happy-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        workload="wide-4",
        path="D",
        workScale=0.5,
    )

    res_id = start_saga_d(envelope, timeout_sec=60)
    assert res_id == saga_id

    run = get_run_item(saga_id)
    assert run is not None
    assert run.get("status") == STATUS_COMPLETED

    events = [e.get("event") for e in get_trace_events(saga_id)]
    assert SAGA_COMPLETED in events

    for step in ("Order", "Step1", "Step2", "Step3", "Step4"):
        item = get_step_item(saga_id, step)
        assert item is not None, f"Missing step {step}"
        assert item.get("status") == "COMPLETED"


def test_wide_fan_parallel_vs_lifo_makespan():
    """
    Phase 7B Acceptance Criterion:
    For wide-4 with failure at the last step (Step4), Path D parallel makespan
    is measurably lower than compMode=lifo (assert >= 25% lower at workScale=1).
    """
    # 0. Warm-up to eliminate LocalStack container cold-start drift (SPEC §4 Phase 8)
    saga_id_warm = f"saga-7b-warm-{uuid.uuid4().hex[:8]}"
    env_warm = SagaEnvelope(
        sagaId=saga_id_warm,
        workload="wide-4",
        path="D",
        faults={"Step4": {"forward": "fail"}},
        workScale=0.1,
    )
    start_saga_d(env_warm, timeout_sec=60)

    # 1. Parallel execution
    saga_id_par = f"saga-7b-par-{uuid.uuid4().hex[:8]}"
    env_par = SagaEnvelope(
        sagaId=saga_id_par,
        workload="wide-4",
        path="D",
        faults={"Step4": {"forward": "fail"}},
        compMode="parallel",
        workScale=1.0,
    )

    start_saga_d(env_par, timeout_sec=60)
    run_par = get_run_item(saga_id_par)
    assert run_par.get("status") == STATUS_COMPENSATED

    events_par = get_trace_events(saga_id_par)
    par_start_candidates = [
        e["ts"] for e in events_par if e.get("event") in (LEASE_ACQUIRED, COMP_STARTED)
    ]
    par_end = [e["ts"] for e in events_par if e.get("event") == SAGA_COMPENSATED][0]
    par_start = min(par_start_candidates)
    makespan_par = int(par_end - par_start)

    # 2. LIFO execution
    saga_id_lifo = f"saga-7b-lifo-{uuid.uuid4().hex[:8]}"
    env_lifo = SagaEnvelope(
        sagaId=saga_id_lifo,
        workload="wide-4",
        path="D",
        faults={"Step4": {"forward": "fail"}},
        compMode="lifo",
        workScale=1.0,
    )

    start_saga_d(env_lifo, timeout_sec=60)
    run_lifo = get_run_item(saga_id_lifo)
    assert run_lifo.get("status") == STATUS_COMPENSATED

    events_lifo = get_trace_events(saga_id_lifo)
    lifo_start_candidates = [
        e["ts"] for e in events_lifo if e.get("event") in (LEASE_ACQUIRED, COMP_STARTED)
    ]
    lifo_end = [e["ts"] for e in events_lifo if e.get("event") == SAGA_COMPENSATED][0]
    lifo_start = min(lifo_start_candidates)
    makespan_lifo = int(lifo_end - lifo_start)

    # 3. Calculate reduction
    reduction = (makespan_lifo - makespan_par) / float(makespan_lifo)
    print(f"\n[Phase 7B] Parallel makespan: {makespan_par} ms, LIFO makespan: {makespan_lifo} ms, reduction: {reduction:.2%}")

    # Verify that all compensated steps have compApplied == 1 in both runs
    for sid in (saga_id_par, saga_id_lifo):
        for s in ("Order", "Step1", "Step2", "Step3"):
            item = get_step_item(sid, s)
            assert item is not None
            assert item.get("status") == "COMPENSATED"
            assert int(item.get("compApplied", 0)) == 1

    # Assert >= 25% lower makespan
    assert reduction >= 0.25, (
        f"Expected parallel makespan to be >= 25% lower than LIFO, but got {reduction:.2%} "
        f"(parallel={makespan_par}ms, lifo={makespan_lifo}ms)"
    )
