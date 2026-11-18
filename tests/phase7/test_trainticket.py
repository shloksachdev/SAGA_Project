"""
Purpose: Phase 7A acceptance tests for TrainTicket-derived workload across Paths A, B, C, and D.
Phase: Phase 7A
"""

import time
import uuid
import pytest
from boto3.dynamodb.conditions import Key

from common.aws import get_table
from common.contracts import (
    COMP_COMPLETED,
    COMP_STARTED,
    NOTIFICATION_DLQ,
    SAGA_COMPENSATED,
    SAGA_COMPLETED,
    STATUS_COMPENSATED,
    STATUS_COMPLETED,
    SagaEnvelope,
)
from paths.a.run import start_saga as start_saga_a
from paths.b.run import start_saga as start_saga_b
from paths.c.run import start_saga as start_saga_c
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


# ==============================================================================
# Path A: Pure Orchestration with TrainTicket Workload
# ==============================================================================

def test_trainticket_path_a_happy_path():
    saga_id = f"saga-7a-a-happy-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        workload="trainticket",
        path="A",
        workScale=0.5,
    )

    res_id = start_saga_a(envelope, timeout_sec=60)
    assert res_id == saga_id

    run = get_run_item(saga_id)
    assert run is not None
    assert run.get("status") == STATUS_COMPLETED
    assert run.get("workload") == "trainticket"

    events = get_trace_events(saga_id)
    types = [e.get("event") for e in events]
    assert SAGA_COMPLETED in types


def test_trainticket_path_a_failure_compensation():
    saga_id = f"saga-7a-a-fail-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        workload="trainticket",
        path="A",
        faults={"Payment": {"forward": "fail", "errorName": "PaymentDeclined"}},
        workScale=0.5,
    )

    res_id = start_saga_a(envelope, timeout_sec=60)
    assert res_id == saga_id

    run = get_run_item(saga_id)
    assert run is not None
    assert run.get("status") == STATUS_COMPENSATED

    events = get_trace_events(saga_id)
    types = [e.get("event") for e in events]
    assert SAGA_COMPENSATED in types

    order_step = get_step_item(saga_id, "Order")
    assert order_step is not None
    assert order_step.get("status") == "COMPENSATED"


# ==============================================================================
# Path B: Pure Choreography with TrainTicket Workload
# ==============================================================================

def test_trainticket_path_b_happy_path():
    saga_id = f"saga-7a-b-happy-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        workload="trainticket",
        path="B",
        workScale=0.5,
    )

    res_id = start_saga_b(envelope, timeout_sec=60)
    assert res_id == saga_id

    run = get_run_item(saga_id)
    assert run is not None
    assert run.get("status") == STATUS_COMPLETED

    events = get_trace_events(saga_id)
    types = [e.get("event") for e in events]
    assert SAGA_COMPLETED in types


def test_trainticket_path_b_failure_compensation():
    saga_id = f"saga-7a-b-fail-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        workload="trainticket",
        path="B",
        faults={"Payment": {"forward": "fail", "errorName": "PaymentDeclined"}},
        workScale=0.5,
    )

    res_id = start_saga_b(envelope, timeout_sec=60)
    assert res_id == saga_id

    run = get_run_item(saga_id)
    assert run is not None
    assert run.get("status") == STATUS_COMPENSATED

    events = get_trace_events(saga_id)
    types = [e.get("event") for e in events]
    assert SAGA_COMPENSATED in types


# ==============================================================================
# Path C: Static Hybrid with TrainTicket Workload
# ==============================================================================

def test_trainticket_path_c_happy_path():
    saga_id = f"saga-7a-c-happy-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        workload="trainticket",
        path="C",
        workScale=0.5,
    )

    res_id = start_saga_c(envelope, timeout_sec=60)
    assert res_id == saga_id

    run = get_run_item(saga_id)
    assert run is not None
    assert run.get("status") == STATUS_COMPLETED

    events = get_trace_events(saga_id)
    types = [e.get("event") for e in events]
    assert SAGA_COMPLETED in types


def test_trainticket_path_c_edge_failure():
    saga_id = f"saga-7a-c-edgefail-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        workload="trainticket",
        path="C",
        faults={"Notification": {"forward": "fail"}},
        workScale=0.5,
    )

    res_id = start_saga_c(envelope, timeout_sec=60)
    assert res_id == saga_id

    run = get_run_item(saga_id)
    assert run is not None
    assert run.get("status") == STATUS_COMPLETED
    assert run.get("edgeFailure") is True

    events = get_trace_events(saga_id)
    types = [e.get("event") for e in events]
    assert NOTIFICATION_DLQ in types


# ==============================================================================
# Path D: Dynamic DAG Compensation with TrainTicket Dependency Enforcement
# ==============================================================================

def test_trainticket_path_d_dependency_order():
    """
    TrainTicket workload defines:
      - Order: compensateAfter = ["*"]
      - Payment: compensateAfter = ["Inventory"] (refund only after seat is released)
      - Inventory: compensateAfter = []
      - Notification: failure point
    Assert that Payment compensation starts strictly AFTER Inventory compensation completes.
    Assert that Order compensation starts strictly AFTER Payment compensation completes.
    """
    saga_id = f"saga-7a-d-dep-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        workload="trainticket",
        path="D",
        faults={"Notification": {"forward": "fail"}},
        workScale=0.5,
    )

    res_id = start_saga_d(envelope, timeout_sec=60)
    assert res_id == saga_id

    run = get_run_item(saga_id)
    assert run is not None
    assert run.get("status") == STATUS_COMPENSATED

    events = get_trace_events(saga_id)
    types = [e.get("event") for e in events]
    assert SAGA_COMPENSATED in types

    # Extract timestamps
    inv_done = [e for e in events if e.get("event") == COMP_COMPLETED and e.get("step") == "Inventory"][0]["ts"]
    pay_start = [e for e in events if e.get("event") == COMP_STARTED and e.get("step") == "Payment"][0]["ts"]
    pay_done = [e for e in events if e.get("event") == COMP_COMPLETED and e.get("step") == "Payment"][0]["ts"]
    order_start = [e for e in events if e.get("event") == COMP_STARTED and e.get("step") == "Order"][0]["ts"]

    # In TrainTicket: Inventory -> Payment -> Order
    assert pay_start >= inv_done, f"Payment started at {pay_start} before Inventory completed at {inv_done}"
    assert order_start >= pay_done, f"Order started at {order_start} before Payment completed at {pay_done}"

    # Verify idempotency & no double-effect
    for step_name in ("Inventory", "Payment", "Order"):
        item = get_step_item(saga_id, step_name)
        assert item is not None
        assert item.get("status") == "COMPENSATED"
        assert int(item.get("compApplied", 0)) == 1
