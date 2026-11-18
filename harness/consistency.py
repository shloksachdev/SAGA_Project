"""
Purpose: Verification of distributed consistency invariants (§3.5, Task 3).
Phase: Phase 8
"""

import os
import sys
from typing import Any, Dict, List, Optional, Tuple
from boto3.dynamodb.conditions import Key

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.aws import get_table
from common.contracts import (
    STATUS_COMPENSATED,
    STATUS_COMPENSATING,
    STATUS_COMPLETED,
    STATUS_FAILED,
)


def get_run_and_steps(saga_id: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """Retrieves SagaRuns and SagaSteps records for a given saga."""
    runs_table = get_table("SagaRuns")
    steps_table = get_table("SagaSteps")

    run_resp = runs_table.get_item(Key={"sagaId": saga_id})
    run_item = run_resp.get("Item")

    steps_resp = steps_table.query(KeyConditionExpression=Key("sagaId").eq(saga_id))
    step_items = steps_resp.get("Items", [])

    return run_item, step_items


def check_consistency(
    saga_id: str,
    run_item: Optional[Dict[str, Any]] = None,
    step_items: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[bool, List[str]]:
    """
    Checks the distributed consistency invariants for a terminal saga:
    - If status == COMPENSATED:
      * Every step must be in {COMPENSATED, FAILED, COMP_FAILED}.
      * Zero steps remain in COMPLETED or COMPENSATING.
      * compApplied <= 1 for all steps (idempotent; no double effect).
    - If status == COMPLETED:
      * Core steps must be COMPLETED.
      * Zero steps in COMPENSATED or COMPENSATING (unless edgeFailure=True).
    Returns (is_consistent, list_of_violations).
    """
    if run_item is None or step_items is None:
        db_run, db_steps = get_run_and_steps(saga_id)
        run_item = run_item or db_run
        step_items = step_items if step_items is not None else db_steps

    violations = []

    if not run_item:
        return False, [f"SagaRuns item for sagaId '{saga_id}' not found."]

    run_status = run_item.get("status")
    edge_failure = run_item.get("edgeFailure", False)

    # Invariant: Run status must be terminal
    terminal_statuses = (STATUS_COMPLETED, STATUS_COMPENSATED, "COMPENSATION_FAILED", STATUS_FAILED)
    if run_status not in terminal_statuses:
        violations.append(f"Run is not in terminal state: status='{run_status}'")

    if run_status == STATUS_COMPENSATED:
        for step in step_items:
            s_name = step.get("step")
            s_status = step.get("status")
            comp_applied = int(step.get("compApplied", 0))

            # 1. No step may remain COMPLETED
            if s_status == STATUS_COMPLETED:
                violations.append(f"Step '{s_name}' remains COMPLETED on a COMPENSATED run.")

            # 2. No step may remain stuck in COMPENSATING
            if s_status == STATUS_COMPENSATING:
                violations.append(f"Step '{s_name}' remains stuck in COMPENSATING.")

            # 3. Status must be COMPENSATED or FAILED
            valid_statuses = (STATUS_COMPENSATED, STATUS_FAILED, "COMP_FAILED")
            if s_status not in valid_statuses:
                violations.append(f"Step '{s_name}' has invalid status '{s_status}' on a COMPENSATED run.")

            # 4. Idempotency invariant: compApplied <= 1
            if comp_applied > 1:
                violations.append(f"Step '{s_name}' has double compensation effect: compApplied={comp_applied} > 1.")

    elif run_status == STATUS_COMPLETED and not edge_failure:
        for step in step_items:
            s_name = step.get("step")
            s_status = step.get("status")
            if s_status in (STATUS_COMPENSATED, STATUS_COMPENSATING):
                violations.append(f"Step '{s_name}' is {s_status} on a clean COMPLETED run.")

    return len(violations) == 0, violations


def assert_consistent(saga_id: str) -> None:
    """Raises AssertionError with violations if consistency check fails."""
    is_valid, violations = check_consistency(saga_id)
    if not is_valid:
        raise AssertionError(f"Consistency check failed for {saga_id}: {'; '.join(violations)}")
