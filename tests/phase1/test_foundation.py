"""
Purpose: Phase 1 acceptance unit and integration tests.
Phase: Phase 1
"""

import time
import uuid
import pytest
from common.aws import get_table
from common.contracts import (
    COMP_COMPLETED,
    COMP_DUPLICATE_IGNORED,
    SagaEnvelope,
    STATUS_COMPENSATED,
    STATUS_COMPLETED,
    STEP_COMPLETED,
    STEP_STARTED,
)
from common.steps import (
    begin_compensation,
    begin_forward,
    complete_compensation,
    complete_forward,
)
from common.work import apply_faults, do_work
from common.workloads import (
    InventoryShortage,
    PaymentDeclined,
    StepConfig,
    StepFailure,
    get_workload,
)
import order_handler
import payment_handler
import inventory_handler
import notification_handler


@pytest.fixture(autouse=True)
def setup_tables():
    from infra.provision import provision
    provision()


def test_work_scale_zero_runs_without_sleeping():
    """Requirement (d): workScale=0 runs without sleeping."""
    start = time.perf_counter()
    elapsed = do_work(ms=500, jitter=50, scale=0.0)
    total_time = (time.perf_counter() - start) * 1000.0
    assert elapsed == 0.0
    assert total_time < 50.0  # Must be near-instantaneous


def test_faults_named_errors():
    """Requirement (e): faults makes the named step fail with the named error."""
    env_payment = SagaEnvelope(
        sagaId=f"test-fault-{uuid.uuid4().hex[:6]}",
        path="A",
        workload="order",
        faults={"Payment": {"forward": "fail", "errorName": "PaymentDeclined"}},
    )
    with pytest.raises(PaymentDeclined):
        apply_faults(env_payment, "Payment", phase="forward")

    env_inventory = SagaEnvelope(
        sagaId=f"test-fault-{uuid.uuid4().hex[:6]}",
        path="A",
        workload="order",
        faults={"Inventory": {"forward": "fail", "errorName": "InventoryShortage"}},
    )
    with pytest.raises(InventoryShortage):
        apply_faults(env_inventory, "Inventory", phase="forward")

    # Legacy simulateFailure alias
    env_legacy = SagaEnvelope(
        sagaId=f"test-fault-{uuid.uuid4().hex[:6]}",
        path="A",
        workload="order",
        simulateFailure=True,
    )
    with pytest.raises(PaymentDeclined):
        apply_faults(env_legacy, "Payment", phase="forward")


def test_forward_invoked_twice_applies_once():
    """Requirement (a): forward invoked twice for the same sagaId applies once."""
    saga_id = f"test-fwd-idemp-{uuid.uuid4().hex[:8]}"
    step_name = "Payment"
    wl = get_workload("order")
    cfg = wl.get_step(step_name)

    # First forward call
    r1 = begin_forward(saga_id, step_name, path="A")
    assert r1 == "PROCEED"
    seq1 = complete_forward(saga_id, step_name, cfg, path="A")
    assert seq1 >= 1

    # Second forward call
    r2 = begin_forward(saga_id, step_name, path="A")
    assert r2 == "ALREADY_DONE"

    # Verify SagaSteps record
    steps_table = get_table("SagaSteps")
    item = steps_table.get_item(Key={"sagaId": saga_id, "step": step_name})["Item"]
    assert item["status"] == STATUS_COMPLETED
    assert int(item["seq"]) == seq1


def test_compensation_non_completed_step_returns_noop():
    """Requirement (b): compensation of a non-COMPLETED step returns NOOP."""
    saga_id = f"test-noop-{uuid.uuid4().hex[:8]}"
    step_name = "Inventory"

    # Step was never completed
    res = begin_compensation(saga_id, step_name, path="A")
    assert res == "NOOP"


def test_compensation_twice_yields_correct_counts():
    """Requirement (c): compensation twice yields compApplied == 1, compInvocations == 2."""
    saga_id = f"test-comp-twice-{uuid.uuid4().hex[:8]}"
    step_name = "Payment"
    wl = get_workload("order")
    cfg = wl.get_step(step_name)

    # Complete the forward step first
    assert begin_forward(saga_id, step_name, path="A") == "PROCEED"
    complete_forward(saga_id, step_name, cfg, path="A")

    # First compensation invocation
    r1 = begin_compensation(saga_id, step_name, path="A")
    assert r1 == "PROCEED"
    applied1 = complete_compensation(saga_id, step_name, path="A")
    assert applied1 is True

    # Second compensation invocation
    r2 = begin_compensation(saga_id, step_name, path="A")
    assert r2 == "NOOP"
    applied2 = complete_compensation(saga_id, step_name, path="A")
    assert applied2 is False

    # Check SagaSteps item counts
    steps_table = get_table("SagaSteps")
    item = steps_table.get_item(Key={"sagaId": saga_id, "step": step_name})["Item"]
    assert item["status"] == STATUS_COMPENSATED
    assert int(item["compInvocations"]) == 2
    assert int(item["compApplied"]) == 1


def test_direct_invoke_all_handlers():
    """Direct invoke of each handler with an envelope produces correct SagaSteps and SagaTrace rows."""
    saga_id = f"test-direct-{uuid.uuid4().hex[:8]}"
    envelope = SagaEnvelope(
        sagaId=saga_id,
        path="A",
        workload="order",
        workScale=0.0,
    )

    # 1. Order create
    res_order = order_handler.lambda_handler(
        {**envelope.to_dict(), "action": "create"}, None
    )
    assert res_order["status"] == "ORDER_CREATED"

    # 2. Payment charge
    res_pay = payment_handler.lambda_handler(
        {**envelope.to_dict(), "action": "charge"}, None
    )
    assert res_pay["status"] == "PAYMENT_COMPLETED"

    # 3. Inventory reserve
    res_inv = inventory_handler.lambda_handler(
        {**envelope.to_dict(), "action": "reserve"}, None
    )
    assert res_inv["status"] == "INVENTORY_RESERVED"

    # 4. Notification notify
    res_notif = notification_handler.lambda_handler(
        {**envelope.to_dict(), "action": "notify"}, None
    )
    assert res_notif["status"] == "NOTIFICATION_SENT"

    # Verify SagaSteps table has all 4 steps COMPLETED
    steps_table = get_table("SagaSteps")
    for step in ["Order", "Payment", "Inventory", "Notification"]:
        resp = steps_table.get_item(Key={"sagaId": saga_id, "step": step})
        assert "Item" in resp, f"Step {step} missing in SagaSteps"
        assert resp["Item"]["status"] == STATUS_COMPLETED
        assert "seq" in resp["Item"]
        assert "compensatorFn" in resp["Item"]

    # Verify SagaTrace table has recorded events
    trace_table = get_table("SagaTrace")
    from boto3.dynamodb.conditions import Key
    trace_resp = trace_table.query(
        KeyConditionExpression=Key("sagaId").eq(saga_id)
    )
    events = [item["event"] for item in trace_resp.get("Items", [])]
    assert STEP_STARTED in events
    assert STEP_COMPLETED in events
