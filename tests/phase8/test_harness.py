"""
Purpose: Phase 8 acceptance tests for metrics derivation, consistency invariants,
coupling metrics, and cost modeling.
"""

import pytest
from common.contracts import (
    COMP_COMPLETED,
    COMP_NEEDED_PUBLISHED,
    COMP_STARTED,
    DDB_OPS,
    EVENTS_PUT,
    LAMBDA_END,
    LAMBDA_INVOKE,
    LEASE_ACQUIRED,
    NOTIFICATION_DLQ,
    SAGA_COMPENSATED,
    SAGA_COMPLETED,
    SAGA_STARTED,
    SFN_TRANSITIONS,
    STATUS_COMPENSATED,
    STATUS_COMPENSATING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STEP_COMPLETED,
    STEP_FAILED,
    STEP_STARTED,
)
from harness.consistency import assert_consistent, check_consistency
from harness.cost import calculate_run_cost, format_cost_table, load_pricing
from harness.coupling import (
    count_asl_lambda_refs,
    count_orchestrator_static_refs,
    evaluate_coupling,
)
from harness.derive import derive_metrics


def test_derive_metrics_happy_trace_known_timestamps():
    """Derive metrics on a synthetic happy trace with known, deterministic timestamps."""
    events = [
        {"sagaId": "saga-happy-1", "event": SAGA_STARTED, "ts": 1000, "sk": "0001", "path": "A", "workload": "order"},
        {"sagaId": "saga-happy-1", "event": STEP_STARTED, "ts": 1050, "sk": "0002"},
        {"sagaId": "saga-happy-1", "event": LAMBDA_INVOKE, "ts": 1050, "sk": "0003"},
        {"sagaId": "saga-happy-1", "event": LAMBDA_END, "ts": 1150, "sk": "0004", "detail": {"durationMs": 100.0}},
        {"sagaId": "saga-happy-1", "event": STEP_COMPLETED, "ts": 1150, "sk": "0005"},
        {"sagaId": "saga-happy-1", "event": SFN_TRANSITIONS, "ts": 1151, "sk": "0006", "detail": {"transitions": 2}},
        {"sagaId": "saga-happy-1", "event": STEP_STARTED, "ts": 1200, "sk": "0007"},
        {"sagaId": "saga-happy-1", "event": LAMBDA_INVOKE, "ts": 1200, "sk": "0008"},
        {"sagaId": "saga-happy-1", "event": LAMBDA_END, "ts": 1350, "sk": "0009", "detail": {"durationMs": 150.0}},
        {"sagaId": "saga-happy-1", "event": STEP_COMPLETED, "ts": 1350, "sk": "0010"},
        {"sagaId": "saga-happy-1", "event": SFN_TRANSITIONS, "ts": 1351, "sk": "0011", "detail": {"transitions": 2}},
        {"sagaId": "saga-happy-1", "event": DDB_OPS, "ts": 1360, "sk": "0012", "detail": {"op": "put", "wru": 2}},
        {"sagaId": "saga-happy-1", "event": DDB_OPS, "ts": 1365, "sk": "0013", "detail": {"op": "get", "rru": 1}},
        {"sagaId": "saga-happy-1", "event": SAGA_COMPLETED, "ts": 1500, "sk": "0014"},
    ]

    metrics = derive_metrics(events)

    # 1. Happy latency: 1500 - 1000 = 500 ms
    assert metrics["happy_latency"] == 500
    assert metrics["compensation_latency"] is None
    assert metrics["election_time"] is None
    assert metrics["scheduling_makespan"] is None

    # 2. Resource usage
    assert metrics["lambda_invocations"] == 2
    assert metrics["lambda_duration_ms"] == 250.0
    assert metrics["step_functions_transitions"] == 4
    assert metrics["dynamodb_wru"] == 2
    assert metrics["dynamodb_rru"] == 1
    assert metrics["eventbridge_events"] == 0
    assert metrics["sqs_requests"] == 0


def test_derive_metrics_compensation_trace_known_timestamps():
    """Derive metrics on a synthetic Path D compensation trace with known timestamps."""
    events = [
        {"sagaId": "saga-comp-1", "event": SAGA_STARTED, "ts": 5000, "sk": "0001", "path": "D", "workload": "order"},
        {"sagaId": "saga-comp-1", "event": STEP_STARTED, "ts": 5050, "sk": "0002"},
        {"sagaId": "saga-comp-1", "event": STEP_COMPLETED, "ts": 5150, "sk": "0003"},
        {"sagaId": "saga-comp-1", "event": STEP_STARTED, "ts": 5200, "sk": "0004"},
        {"sagaId": "saga-comp-1", "event": STEP_FAILED, "ts": 5300, "sk": "0005"},
        {"sagaId": "saga-comp-1", "event": COMP_NEEDED_PUBLISHED, "ts": 5320, "sk": "0006"},
        {"sagaId": "saga-comp-1", "event": EVENTS_PUT, "ts": 5320, "sk": "0007"},
        {"sagaId": "saga-comp-1", "event": LEASE_ACQUIRED, "ts": 5400, "sk": "0008"},
        {"sagaId": "saga-comp-1", "event": COMP_STARTED, "ts": 5450, "sk": "0009"},
        {"sagaId": "saga-comp-1", "event": COMP_COMPLETED, "ts": 5600, "sk": "0010"},
        {"sagaId": "saga-comp-1", "event": SAGA_COMPENSATED, "ts": 5700, "sk": "0011"},
    ]

    metrics = derive_metrics(events)

    assert metrics["happy_latency"] is None
    # compensation_latency: SAGA_COMPENSATED (5700) - STEP_FAILED (5300) = 400
    assert metrics["compensation_latency"] == 400
    # election_time: LEASE_ACQUIRED (5400) - COMP_NEEDED_PUBLISHED (5320) = 80
    assert metrics["election_time"] == 80
    # scheduling_makespan: SAGA_COMPENSATED (5700) - LEASE_ACQUIRED (5400) = 300
    assert metrics["scheduling_makespan"] == 300


def test_consistency_checker_valid_runs():
    """Verify clean happy and compensated runs pass invariant checks without violations."""
    # 1. Clean happy run
    happy_run = {"sagaId": "saga-h-1", "status": STATUS_COMPLETED, "edgeFailure": False}
    happy_steps = [
        {"step": "Order", "status": STATUS_COMPLETED, "compApplied": 0},
        {"step": "Payment", "status": STATUS_COMPLETED, "compApplied": 0},
        {"step": "Inventory", "status": STATUS_COMPLETED, "compApplied": 0},
        {"step": "Notification", "status": STATUS_COMPLETED, "compApplied": 0},
    ]
    is_valid, violations = check_consistency("saga-h-1", run_item=happy_run, step_items=happy_steps)
    assert is_valid is True
    assert len(violations) == 0

    # 2. Clean compensated run
    comp_run = {"sagaId": "saga-c-1", "status": STATUS_COMPENSATED}
    comp_steps = [
        {"step": "Order", "status": STATUS_COMPENSATED, "compApplied": 1},
        {"step": "Payment", "status": STATUS_FAILED, "compApplied": 0},
    ]
    is_valid, violations = check_consistency("saga-c-1", run_item=comp_run, step_items=comp_steps)
    assert is_valid is True
    assert len(violations) == 0


def test_consistency_checker_negative_corrupted_runs():
    """Negative tests: deliberately corrupt run/step data and verify invariant detector flags them."""
    # Negative Test 1: Step remains COMPLETED on a COMPENSATED run
    corrupt_run_1 = {"sagaId": "saga-bad-1", "status": STATUS_COMPENSATED}
    corrupt_steps_1 = [
        {"step": "Order", "status": STATUS_COMPENSATED, "compApplied": 1},
        {"step": "Payment", "status": STATUS_COMPLETED, "compApplied": 0},  # Violation!
    ]
    is_valid, violations = check_consistency("saga-bad-1", run_item=corrupt_run_1, step_items=corrupt_steps_1)
    assert is_valid is False
    assert any("remains COMPLETED" in v for v in violations)

    # Negative Test 2: compApplied > 1 (Double compensation effect)
    corrupt_run_2 = {"sagaId": "saga-bad-2", "status": STATUS_COMPENSATED}
    corrupt_steps_2 = [
        {"step": "Order", "status": STATUS_COMPENSATED, "compApplied": 2},  # Violation!
        {"step": "Payment", "status": STATUS_FAILED, "compApplied": 0},
    ]
    is_valid, violations = check_consistency("saga-bad-2", run_item=corrupt_run_2, step_items=corrupt_steps_2)
    assert is_valid is False
    assert any("double compensation effect" in v for v in violations)

    # Negative Test 3: Step stuck in COMPENSATING
    corrupt_run_3 = {"sagaId": "saga-bad-3", "status": STATUS_COMPENSATED}
    corrupt_steps_3 = [
        {"step": "Order", "status": STATUS_COMPENSATING, "compApplied": 0},  # Violation!
        {"step": "Payment", "status": STATUS_FAILED, "compApplied": 0},
    ]
    is_valid, violations = check_consistency("saga-bad-3", run_item=corrupt_run_3, step_items=corrupt_steps_3)
    assert is_valid is False
    assert any("stuck in COMPENSATING" in v for v in violations)

    # Negative Test 4: Step is COMPENSATED on a clean COMPLETED run
    corrupt_run_4 = {"sagaId": "saga-bad-4", "status": STATUS_COMPLETED, "edgeFailure": False}
    corrupt_steps_4 = [
        {"step": "Order", "status": STATUS_COMPENSATED, "compApplied": 1},  # Violation!
    ]
    is_valid, violations = check_consistency("saga-bad-4", run_item=corrupt_run_4, step_items=corrupt_steps_4)
    assert is_valid is False
    assert any("is COMPENSATED on a clean COMPLETED run" in v for v in violations)

    # Negative Test 5: assert_consistent raises AssertionError
    with pytest.raises(AssertionError) as exc_info:
        assert_consistent("saga-bad-1")
    assert "Consistency check failed" in str(exc_info.value) or "not found" in str(exc_info.value)


def test_coupling_metrics_evaluation():
    """Verify architectural coupling metrics across all paths and D5 orchestrator static reference count."""
    # 1. Test D5 constraint: Dynamic orchestrator static references must be exactly 0
    static_refs = count_orchestrator_static_refs()
    assert static_refs == 0, f"Expected 0 orchestrator static service references (D5), found {static_refs}"

    # 2. Test ASL Lambda ARN reference counter
    sample_asl = {
        "States": {
            "State1": {"Resource": "arn:aws:lambda:us-east-1:000000000000:function:Order"},
            "State2": {"Resource": "arn:aws:lambda:us-east-1:000000000000:function:Payment"},
            "State3": {"Resource": "arn:aws:lambda:us-east-1:000000000000:function:Order"},  # duplicate ARN
            "StatePass": {"Type": "Pass"},
        }
    }
    assert count_asl_lambda_refs(sample_asl) == 2

    # 3. Test coupling evaluation for order workload
    coupling = evaluate_coupling("order")
    assert "A" in coupling
    assert "B" in coupling
    assert "C" in coupling
    assert "D" in coupling

    # Path A: 4 ASL Lambda references, 0 EB rules
    assert coupling["A"]["asl_refs"] == 4
    assert coupling["A"]["eb_total_rules"] == 0

    # Path B: 0 ASL refs, 4 forward + 3 comp EB rules = 7 rules
    assert coupling["B"]["asl_refs"] == 0
    assert coupling["B"]["eb_forward_rules"] == 4
    assert coupling["B"]["eb_comp_rules"] == 3
    assert coupling["B"]["eb_total_rules"] == 7

    # Path C: 3 core ASL refs + 1 edge EB rule = 4
    assert coupling["C"]["asl_refs"] == 3
    assert coupling["C"]["eb_forward_rules"] == 1
    assert coupling["C"]["total_coupling"] == 4

    # Path D: 4 forward EB rules + 1 election fan-in rule = 5 total, 0 static orchestrator refs
    assert coupling["D"]["asl_refs"] == 0
    assert coupling["D"]["eb_total_rules"] == 5
    assert coupling["D"]["orchestrator_static_refs"] == 0


def test_cost_model_and_pricing_calculation():
    """Verify cost calculation against AWS list pricing table."""
    pricing = load_pricing()
    assert pricing["currency"] == "USD"
    assert "lambda" in pricing["services"]
    assert "eventbridge" in pricing["services"]
    assert "step_functions" in pricing["services"]
    assert "dynamodb" in pricing["services"]
    assert "sqs" in pricing["services"]

    # Test single run cost derivation
    # 4 invocations, 600ms total duration, 128MB memory
    # memory: 128MB = 0.125 GB
    # compute sec: 0.600 s -> 0.600 * 0.125 = 0.075 GB-s
    # lambda request cost: 4 * 0.0000002 = 0.0000008
    # lambda compute cost: 0.075 * 0.0000166667 = 0.0000012500025
    # total lambda = ~0.00000205
    sample_metrics = {
        "lambda_invocations": 4,
        "lambda_duration_ms": 600.0,
        "eventbridge_events": 4,  # 4 * 0.000001 = 0.000004
        "step_functions_transitions": 6,  # 6 * 0.000025 = 0.000150
        "dynamodb_wru": 4,  # 4 * 0.00000025 = 0.000001
        "dynamodb_rru": 2,  # 2 * 0.00000005 = 0.0000001
        "sqs_requests": 0,
    }

    cost = calculate_run_cost(sample_metrics, pricing=pricing, memory_mb=128)
    assert cost["lambda_invocations"] == 4
    assert cost["eventbridge_events"] == 4
    assert cost["step_functions_transitions"] == 6
    assert cost["total_cost"] > 0
    assert cost["cost_per_1000"] == pytest.approx(cost["total_cost"] * 1000.0, rel=1e-6)

    # Format table test
    table_str = format_cost_table({"A": cost})
    assert "| **A** |" in table_str
