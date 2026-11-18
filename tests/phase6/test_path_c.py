"""
Purpose: Phase 6 acceptance tests for Path C (static hybrid: SFN core + EventBridge edge).
Phase: Phase 6
"""

import json
import time
import uuid
import pytest
from boto3.dynamodb.conditions import Key

from common.aws import get_boto3_client, get_table
from common.contracts import (
    NOTIFICATION_DLQ,
    SAGA_COMPENSATED,
    SAGA_COMPLETED,
    SAGA_STARTED,
    STATUS_COMPENSATED,
    STATUS_COMPLETED,
    STEP_FAILED,
    SagaEnvelope,
)
from paths.c.provision import DLQ_QUEUE_NAME, provision as provision_path_c
from paths.c.run import start_saga


@pytest.fixture(scope="module", autouse=True)
def setup_path_c():
    provision_path_c()


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


def test_happy_path_hybrid():
    """Happy path completes via the edge (Notification)."""
    saga_id = f"test-c-happy-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        path="C",
        workload="order",
        workScale=0.0,
    )

    start_saga(envelope, timeout_sec=60)

    run = get_run_item(saga_id)
    assert run is not None
    assert run["status"] == STATUS_COMPLETED
    assert not run.get("edgeFailure")

    trace = get_trace_events(saga_id)
    events = [t["event"] for t in trace]
    assert SAGA_STARTED in events
    assert SAGA_COMPLETED in events

    # All 4 steps must be COMPLETED
    for s in ("Order", "Payment", "Inventory", "Notification"):
        item = get_step_item(saga_id, s)
        assert item is not None, f"Step {s} record missing"
        assert item["status"] == STATUS_COMPLETED
        assert int(item.get("compApplied", 0)) == 0


def test_failure_at_payment():
    """Failure at Payment: core compensated in reverse order, Notification never ran."""
    saga_id = f"test-c-payfail-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        path="C",
        workload="order",
        workScale=0.0,
        faults={"Payment": {"forward": "fail", "errorName": "PaymentDeclined"}},
    )

    start_saga(envelope, timeout_sec=60)

    run = get_run_item(saga_id)
    assert run is not None
    assert run["status"] == STATUS_COMPENSATED

    trace = get_trace_events(saga_id)
    events = [t["event"] for t in trace]
    assert SAGA_COMPENSATED in events

    # Order must be compensated
    order_step = get_step_item(saga_id, "Order")
    assert order_step is not None
    assert order_step["status"] == STATUS_COMPENSATED
    assert int(order_step.get("compApplied", 0)) == 1

    # Payment failed, not compensated
    payment_step = get_step_item(saga_id, "Payment")
    assert payment_step is not None
    assert payment_step["status"] == "FAILED"
    assert int(payment_step.get("compApplied", 0)) == 0

    # Inventory and Notification never ran
    inv_step = get_step_item(saga_id, "Inventory")
    assert inv_step is None

    notif_step = get_step_item(saga_id, "Notification")
    assert notif_step is None


def test_failure_at_inventory():
    """Failure at Inventory: core compensated in reverse order, Notification never ran."""
    saga_id = f"test-c-invfail-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        path="C",
        workload="order",
        workScale=0.0,
        faults={"Inventory": {"forward": "fail", "errorName": "InventoryShortage"}},
    )

    start_saga(envelope, timeout_sec=60)

    run = get_run_item(saga_id)
    assert run is not None
    assert run["status"] == STATUS_COMPENSATED

    trace = get_trace_events(saga_id)
    events = [t["event"] for t in trace]
    assert SAGA_COMPENSATED in events

    # Payment and Order must be compensated
    pay_step = get_step_item(saga_id, "Payment")
    order_step = get_step_item(saga_id, "Order")
    assert pay_step is not None and pay_step["status"] == STATUS_COMPENSATED
    assert order_step is not None and order_step["status"] == STATUS_COMPENSATED
    assert int(pay_step.get("compApplied", 0)) == 1
    assert int(order_step.get("compApplied", 0)) == 1

    # Inventory was the failing step
    inv_step = get_step_item(saga_id, "Inventory")
    assert inv_step is not None and inv_step["status"] == "FAILED"
    assert int(inv_step.get("compApplied", 0)) == 0

    # Notification never ran
    notif_step = get_step_item(saga_id, "Notification")
    assert notif_step is None

    # Reverse order verification: Payment compensated before Order
    assert pay_step["compensatedAt"] <= order_step["compensatedAt"]


def test_notification_forced_to_fail():
    """
    Notification forced to fail:
    - NOTIFICATION_DLQ event emitted.
    - DLQ has the message.
    - Core steps remain COMPLETED.
    - Run status reflects completed with edge failure (COMPLETED with edgeFailure=True).
    - Core is NOT rolled back (no SAGA_COMPENSATED).
    """
    saga_id = f"test-c-notiffail-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        path="C",
        workload="order",
        workScale=0.0,
        faults={"Notification": {"forward": "fail"}},
    )

    start_saga(envelope, timeout_sec=60)

    run = get_run_item(saga_id)
    assert run is not None
    assert run["status"] == STATUS_COMPLETED
    assert run.get("edgeFailure") is True

    trace = get_trace_events(saga_id)
    events = [t["event"] for t in trace]
    assert NOTIFICATION_DLQ in events
    assert SAGA_COMPENSATED not in events

    # Core steps remain COMPLETED
    for s in ("Order", "Payment", "Inventory"):
        item = get_step_item(saga_id, s)
        assert item is not None
        assert item["status"] == STATUS_COMPLETED
        assert int(item.get("compApplied", 0)) == 0

    # Notification step is FAILED
    notif_step = get_step_item(saga_id, "Notification")
    assert notif_step is not None
    assert notif_step["status"] == "FAILED"

    # DLQ has the message
    sqs = get_boto3_client("sqs")
    queue_url = sqs.get_queue_url(QueueName=DLQ_QUEUE_NAME)["QueueUrl"]
    resp = sqs.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=10,
        WaitTimeSeconds=2,
    )
    messages = resp.get("Messages", [])
    found_saga_in_dlq = False
    for msg in messages:
        try:
            body = json.loads(msg["Body"])
            if body.get("sagaId") == saga_id:
                found_saga_in_dlq = True
                # Clean up DLQ message
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"])
                break
        except Exception:
            pass

    assert found_saga_in_dlq, f"Expected message for sagaId {saga_id} in SQS DLQ {DLQ_QUEUE_NAME}"
