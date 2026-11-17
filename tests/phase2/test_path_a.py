"""
Purpose: Phase 2 acceptance tests for Path A (pure orchestration).
Phase: Phase 2
"""

import uuid
import pytest
from boto3.dynamodb.conditions import Key
from common.aws import get_table
from common.contracts import (
    COMP_FAILED_ATTEMPT,
    SAGA_COMPENSATED,
    SAGA_COMPLETED,
    SAGA_STARTED,
    STATUS_COMPENSATED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STEP_FAILED,
    SagaEnvelope,
)
from infra.provision import provision
from paths.a.deploy import deploy
from paths.a.run import start_saga
import order_handler


@pytest.fixture(scope="module", autouse=True)
def setup_path_a():
    provision()
    deploy()


def get_trace_events(saga_id: str):
    trace_table = get_table("SagaTrace")
    resp = trace_table.query(KeyConditionExpression=Key("sagaId").eq(saga_id))
    return resp.get("Items", [])


def get_step_item(saga_id: str, step: str):
    steps_table = get_table("SagaSteps")
    resp = steps_table.get_item(Key={"sagaId": saga_id, "step": step})
    return resp.get("Item")


def get_run_item(saga_id: str):
    runs_table = get_table("SagaRuns")
    resp = runs_table.get_item(Key={"sagaId": saga_id})
    return resp.get("Item")


def test_happy_path_orchestration():
    """Happy run: SagaRuns.status == COMPLETED, 4 steps COMPLETED."""
    saga_id = f"test-a-happy-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        path="A",
        workload="order",
        workScale=0.0,
    )

    start_saga(envelope, timeout_sec=30)

    run = get_run_item(saga_id)
    assert run is not None
    assert run["status"] == STATUS_COMPLETED

    for step in ["Order", "Payment", "Inventory", "Notification"]:
        item = get_step_item(saga_id, step)
        assert item is not None, f"Step {step} was not recorded"
        assert item["status"] == STATUS_COMPLETED
        assert int(item["seq"]) >= 1

    events = [item["event"] for item in get_trace_events(saga_id)]
    assert SAGA_STARTED in events
    assert SAGA_COMPLETED in events


def test_failure_at_payment():
    """
    Failure at Payment:
    - SagaRuns.status == COMPENSATED
    - Exactly Order (completed prior) is COMPENSATED
    - Payment is FAILED and not compensated
    - Inventory and Notification never ran
    - Trace has STEP_FAILED then SAGA_COMPENSATED
    """
    saga_id = f"test-a-fail-pay-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        path="A",
        workload="order",
        workScale=0.0,
        faults={"Payment": {"forward": "fail", "errorName": "PaymentDeclined"}},
    )

    start_saga(envelope, timeout_sec=30)

    run = get_run_item(saga_id)
    assert run is not None
    assert run["status"] == STATUS_COMPENSATED

    order_item = get_step_item(saga_id, "Order")
    assert order_item is not None
    assert order_item["status"] == STATUS_COMPENSATED
    assert int(order_item["compApplied"]) == 1

    pay_item = get_step_item(saga_id, "Payment")
    assert pay_item is not None
    assert pay_item["status"] == STATUS_FAILED
    assert "compApplied" not in pay_item or int(pay_item["compApplied"]) == 0

    assert get_step_item(saga_id, "Inventory") is None
    assert get_step_item(saga_id, "Notification") is None

    trace = get_trace_events(saga_id)
    events = [t["event"] for t in trace]
    assert STEP_FAILED in events
    assert SAGA_COMPENSATED in events
    idx_fail = events.index(STEP_FAILED)
    idx_comp = events.index(SAGA_COMPENSATED)
    assert idx_fail < idx_comp


def test_failure_at_inventory():
    """
    Failure at Inventory:
    - SagaRuns.status == COMPENSATED
    - Order and Payment are COMPENSATED in reverse order by seq
    - Inventory is FAILED and not compensated
    - Notification never ran
    """
    saga_id = f"test-a-fail-inv-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        path="A",
        workload="order",
        workScale=0.0,
        faults={"Inventory": {"forward": "fail", "errorName": "InventoryShortage"}},
    )

    start_saga(envelope, timeout_sec=30)

    run = get_run_item(saga_id)
    assert run is not None
    assert run["status"] == STATUS_COMPENSATED

    order_item = get_step_item(saga_id, "Order")
    pay_item = get_step_item(saga_id, "Payment")
    inv_item = get_step_item(saga_id, "Inventory")

    assert order_item["status"] == STATUS_COMPENSATED
    assert int(order_item["compApplied"]) == 1
    assert pay_item["status"] == STATUS_COMPENSATED
    assert int(pay_item["compApplied"]) == 1

    # Check reverse seq ordering: Payment seq > Order seq, but Payment compensated before Order
    assert int(pay_item["seq"]) > int(order_item["seq"])
    assert int(pay_item["compensatedAt"]) <= int(order_item["compensatedAt"])

    assert inv_item["status"] == STATUS_FAILED
    assert "compApplied" not in inv_item or int(inv_item["compApplied"]) == 0
    assert get_step_item(saga_id, "Notification") is None

    events = [t["event"] for t in get_trace_events(saga_id)]
    assert STEP_FAILED in events
    assert SAGA_COMPENSATED in events


def test_failure_at_notification():
    """
    Failure at Notification:
    - SagaRuns.status == COMPENSATED
    - Order, Payment, Inventory all COMPENSATED in reverse order
    - Notification is FAILED
    """
    saga_id = f"test-a-fail-notif-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        path="A",
        workload="order",
        workScale=0.0,
        faults={"Notification": {"forward": "fail", "errorName": "StepFailure"}},
    )

    start_saga(envelope, timeout_sec=30)

    run = get_run_item(saga_id)
    assert run is not None
    assert run["status"] == STATUS_COMPENSATED

    order_item = get_step_item(saga_id, "Order")
    pay_item = get_step_item(saga_id, "Payment")
    inv_item = get_step_item(saga_id, "Inventory")
    notif_item = get_step_item(saga_id, "Notification")

    assert order_item["status"] == STATUS_COMPENSATED
    assert pay_item["status"] == STATUS_COMPENSATED
    assert inv_item["status"] == STATUS_COMPENSATED
    assert notif_item["status"] == STATUS_FAILED

    # Reverse order: Inventory -> Payment -> Order
    assert int(inv_item["compensatedAt"]) <= int(pay_item["compensatedAt"]) <= int(order_item["compensatedAt"])

    events = [t["event"] for t in get_trace_events(saga_id)]
    assert STEP_FAILED in events
    assert SAGA_COMPENSATED in events


def test_transient_compensation_failure_with_retry():
    """
    compFailFirstN=1 on one step:
    - Run still ends COMPENSATED (Step Functions retry worked)
    - Trace shows one COMP_FAILED_ATTEMPT
    """
    saga_id = f"test-a-retry-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        path="A",
        workload="order",
        workScale=0.0,
        faults={
            "Payment": {"forward": "fail"},
            "Order": {"compFailFirstN": 1},
        },
    )

    start_saga(envelope, timeout_sec=40)

    run = get_run_item(saga_id)
    assert run is not None
    assert run["status"] == STATUS_COMPENSATED

    order_item = get_step_item(saga_id, "Order")
    assert order_item["status"] == STATUS_COMPENSATED
    assert int(order_item["compApplied"]) == 1
    assert int(order_item["compInvocations"]) == 2

    events = [t["event"] for t in get_trace_events(saga_id)]
    assert COMP_FAILED_ATTEMPT in events
    assert SAGA_COMPENSATED in events


def test_duplicate_safe_compensation():
    """Duplicate-safe: re-running a compensation task directly leaves compApplied == 1."""
    saga_id = f"test-a-dup-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        path="A",
        workload="order",
        workScale=0.0,
        faults={"Payment": {"forward": "fail"}},
    )

    start_saga(envelope, timeout_sec=30)

    # First compensation was completed by Step Functions
    order_item = get_step_item(saga_id, "Order")
    assert order_item["status"] == STATUS_COMPENSATED
    assert int(order_item["compApplied"]) == 1

    # Directly re-run compensation on Order
    res = order_handler.lambda_handler(
        {**envelope.to_dict(), "action": "cancel"}, None
    )
    assert res["status"] == "ORDER_CANCELLED"

    # Verify compApplied is still 1
    order_item_after = get_step_item(saga_id, "Order")
    assert int(order_item_after["compApplied"]) == 1
