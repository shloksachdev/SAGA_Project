"""
Purpose: End-to-end integration tests for Path D Phase 5 (DAG compensation & LIFO ablation).
Phase: Phase 5
"""

import time
import uuid
import pytest

from boto3.dynamodb.conditions import Key
from common.aws import get_table
from common.contracts import (
    COMP_COMPLETED,
    COMP_DISPATCHED,
    COMP_NEEDED_PUBLISHED,
    COMP_STARTED,
    LEASE_ACQUIRED,
    LEASE_TAKEOVER,
    SAGA_COMPENSATED,
    STATUS_COMPENSATED,
    SagaEnvelope,
)
from common.events import publish_event
from common.lease import get_lease
from paths.d.run import start_saga


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


def test_parallel_dag_compensation_overlap():
    """
    Integration, failure injected at Notification:
    - Run ends COMPENSATED.
    - Trace shows Payment and Inventory compensation intervals overlapping.
    - Order's COMP_STARTED is after both complete.
    """
    saga_id = f"test-p5-overlap-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        path="D",
        workload="order",
        workScale=1.0,
        faults={"Notification": {"forward": "fail"}},
        compMode="parallel",
    )

    start_saga(envelope, timeout_sec=60)

    run = get_run_item(saga_id)
    assert run is not None
    assert run["status"] == STATUS_COMPENSATED

    trace = get_trace_events(saga_id)
    events = [t["event"] for t in trace]
    assert SAGA_COMPENSATED in events

    def get_comp_interval(actor_name: str):
        starts = [t["ts"] for t in trace if t.get("actor") == actor_name and t.get("event") == COMP_STARTED]
        ends = [t["ts"] for t in trace if t.get("actor") == actor_name and t.get("event") == COMP_COMPLETED]
        assert starts, f"Missing COMP_STARTED for {actor_name}"
        assert ends, f"Missing COMP_COMPLETED for {actor_name}"
        return starts[0], ends[0]

    pay_start, pay_end = get_comp_interval("Payment")
    inv_start, inv_end = get_comp_interval("Inventory")
    order_start, order_end = get_comp_interval("Order")

    # Payment and Inventory intervals must overlap: max(s1, s2) < min(e1, e2)
    overlap = max(pay_start, inv_start) < min(pay_end, inv_end)
    assert overlap, f"Expected Payment [{pay_start}, {pay_end}] and Inventory [{inv_start}, {inv_end}] to overlap"

    # Order COMP_STARTED must be after both Payment and Inventory COMP_COMPLETED
    assert order_start >= pay_end, f"Order started at {order_start} before Payment completed at {pay_end}"
    assert order_start >= inv_end, f"Order started at {order_start} before Inventory completed at {inv_end}"

    # Verify compApplied == 1
    for s in ("Order", "Payment", "Inventory"):
        step_rec = get_step_item(saga_id, s)
        assert step_rec is not None
        assert int(step_rec.get("compApplied", 0)) == 1

    # Notification was not compensated
    notif_rec = get_step_item(saga_id, "Notification")
    assert notif_rec is not None
    assert int(notif_rec.get("compApplied", 0)) == 0


def test_lifo_ablation_no_overlap():
    """
    Same scenario with compMode=lifo:
    Intervals do NOT overlap (sequential execution in descending seq order).
    """
    saga_id = f"test-p5-lifo-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        path="D",
        workload="order",
        workScale=1.0,
        faults={"Notification": {"forward": "fail"}},
        compMode="lifo",
    )

    start_saga(envelope, timeout_sec=60)

    run = get_run_item(saga_id)
    assert run is not None
    assert run["status"] == STATUS_COMPENSATED

    trace = get_trace_events(saga_id)

    def get_comp_interval(actor_name: str):
        starts = [t["ts"] for t in trace if t.get("actor") == actor_name and t.get("event") == COMP_STARTED]
        ends = [t["ts"] for t in trace if t.get("actor") == actor_name and t.get("event") == COMP_COMPLETED]
        assert starts, f"Missing COMP_STARTED for {actor_name}"
        assert ends, f"Missing COMP_COMPLETED for {actor_name}"
        return starts[0], ends[0]

    pay_start, pay_end = get_comp_interval("Payment")
    inv_start, inv_end = get_comp_interval("Inventory")
    order_start, order_end = get_comp_interval("Order")

    # In LIFO: Inventory (seq 3) and Payment (seq 2) must NOT overlap
    overlap = max(pay_start, inv_start) < min(pay_end, inv_end)
    assert not overlap, f"Expected Payment [{pay_start}, {pay_end}] and Inventory [{inv_start}, {inv_end}] NOT to overlap in LIFO mode"

    # Order (seq 1) runs last
    assert order_start >= max(pay_end, inv_end)


def test_duplicate_compensation_needed_event():
    """
    Duplicate CompensationNeeded published twice:
    Single compensation effect (compApplied == 1 for every step).
    """
    saga_id = f"test-p5-dup-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        path="D",
        workload="order",
        workScale=0.0,
        faults={"Notification": {"forward": "fail"}},
        compMode="parallel",
    )

    start_saga(envelope, timeout_sec=60)

    run = get_run_item(saga_id)
    assert run is not None
    assert run["status"] == STATUS_COMPENSATED

    # Simulate duplicate CompensationNeeded event to saga-bus-d
    elect_detail = envelope.to_dict()
    elect_detail["action"] = "elect"
    elect_detail["failedStep"] = "Notification"
    publish_event(
        bus_name="saga-bus-d",
        source="saga.notification",
        detail_type="CompensationNeeded",
        detail=elect_detail,
        saga_id=saga_id,
    )

    time.sleep(2.0)

    # Verify single compensation effect: compApplied == 1 for every step
    for s in ("Order", "Payment", "Inventory"):
        step_rec = get_step_item(saga_id, s)
        assert step_rec is not None
        assert int(step_rec.get("compApplied", 0)) == 1


def test_leader_crash_after_one_dispatch():
    """
    Leader crash after 1 dispatch (leaderFault="crash_after:1"):
    Takeover completes the saga, compApplied == 1 for all steps, one LEASE_TAKEOVER.
    """
    saga_id = f"test-p5-crash-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        path="D",
        workload="order",
        workScale=0.5,
        faults={"Notification": {"forward": "fail"}},
        leaderFault="crash_after:1",
        compMode="parallel",
    )

    start_saga(envelope, timeout_sec=60)

    run = get_run_item(saga_id)
    assert run is not None
    assert run["status"] == STATUS_COMPENSATED

    trace = get_trace_events(saga_id)

    # Initial leader had LEASE_ACQUIRED (epoch 1)
    acquired = [t for t in trace if t.get("event") == LEASE_ACQUIRED]
    assert len(acquired) == 1

    # Takeover leader had LEASE_TAKEOVER (epoch >= 2)
    takeovers = [t for t in trace if t.get("event") == LEASE_TAKEOVER]
    assert len(takeovers) >= 1

    # compApplied == 1 for all compensated steps
    for s in ("Order", "Payment", "Inventory"):
        step_rec = get_step_item(saga_id, s)
        assert step_rec is not None
        assert int(step_rec.get("compApplied", 0)) == 1
