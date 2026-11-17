"""
Purpose: Idempotent step state machine over SagaSteps and SagaRuns tables (D5, D8).
Phase: Phase 1
"""

import logging
from typing import Any, Dict, List, Optional
import botocore.exceptions
from common.aws import get_table
from common.contracts import (
    COMP_COMPLETED,
    COMP_DUPLICATE_IGNORED,
    COMP_STARTED,
    SAGA_COMPENSATED,
    STATUS_COMPENSATED,
    STATUS_COMPENSATING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
    STATUS_STARTED,
    STEP_COMPLETED,
    STEP_FAILED,
    STEP_STARTED,
)
from common.trace import emit, now_ms
from common.workloads import StepConfig

logger = logging.getLogger(__name__)

STEPS_TABLE_NAME = "SagaSteps"
RUNS_TABLE_NAME = "SagaRuns"


def begin_forward(saga_id: str, step_name: str, path: Optional[str] = None) -> str:
    """
    Attempts to mark step as STARTED.
    If step is already COMPLETED, returns "ALREADY_DONE" (idempotency, D8).
    Returns "PROCEED" if forward work should be executed.
    """
    steps_table = get_table(STEPS_TABLE_NAME)
    ts = now_ms()

    # First inspect current state
    try:
        resp = steps_table.get_item(Key={"sagaId": saga_id, "step": step_name})
        if "Item" in resp:
            item = resp["Item"]
            status = item.get("status")
            if status == STATUS_COMPLETED:
                return "ALREADY_DONE"
    except Exception as e:
        logger.warning(f"[steps] get_item error in begin_forward: {e}")

    # Conditional put: succeed if attribute_not_exists or status not COMPLETED
    try:
        steps_table.update_item(
            Key={"sagaId": saga_id, "step": step_name},
            UpdateExpression="SET #st = :started, startedAt = :ts",
            ConditionExpression="attribute_not_exists(#st) OR #st <> :completed",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":started": STATUS_STARTED,
                ":ts": ts,
                ":completed": STATUS_COMPLETED,
            },
        )
        emit(saga_id, STEP_STARTED, step=step_name, actor=step_name, path=path)
        return "PROCEED"
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return "ALREADY_DONE"
        raise


def complete_forward(
    saga_id: str,
    step_name: str,
    step_config: StepConfig,
    path: Optional[str] = None,
    order_id: Optional[str] = None,
) -> int:
    """
    Transitions step to COMPLETED.
    Atomically increments stepCounter on SagaRuns to assign completion sequence (seq).
    Records self-declared compensation dependencies in SagaSteps (D5).
    Returns assigned seq.
    """
    steps_table = get_table(STEPS_TABLE_NAME)
    runs_table = get_table(RUNS_TABLE_NAME)
    ts = now_ms()

    # 1. Atomic counter for completion sequence
    seq = 1
    try:
        runs_resp = runs_table.update_item(
            Key={"sagaId": saga_id},
            UpdateExpression="ADD stepCounter :one SET #st = if_not_exists(#st, :running)",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":one": 1, ":running": STATUS_RUNNING},
            ReturnValues="UPDATED_NEW",
        )
        seq = int(runs_resp.get("Attributes", {}).get("stepCounter", 1))
    except Exception as e:
        logger.warning(f"[steps] Failed to update stepCounter on SagaRuns: {e}")

    # 2. Update SagaSteps item
    steps_table.update_item(
        Key={"sagaId": saga_id, "step": step_name},
        UpdateExpression=(
            "SET #st = :completed, seq = :seq, completedAt = :ts, "
            "compensatorFn = :cfn, compensateAction = :cact, "
            "compensateAfter = :caft, compensateOnFailure = :cof"
        ),
        ExpressionAttributeNames={"#st": "status"},
        ExpressionAttributeValues={
            ":completed": STATUS_COMPLETED,
            ":seq": seq,
            ":ts": ts,
            ":cfn": step_config.compensatorFn,
            ":cact": step_config.compensateAction,
            ":caft": step_config.compensateAfter,
            ":cof": step_config.compensateOnFailure,
        },
    )

    emit(saga_id, STEP_COMPLETED, step=step_name, actor=step_name, path=path, seq=seq)
    return seq


def fail_forward(
    saga_id: str,
    step_name: str,
    error: Exception,
    path: Optional[str] = None,
) -> None:
    """
    Marks the forward step as FAILED in SagaSteps and marks SagaRuns as COMPENSATING.
    """
    steps_table = get_table(STEPS_TABLE_NAME)
    runs_table = get_table(RUNS_TABLE_NAME)
    ts = now_ms()
    err_msg = str(error)
    err_cls = error.__class__.__name__

    try:
        steps_table.update_item(
            Key={"sagaId": saga_id, "step": step_name},
            UpdateExpression="SET #st = :failed, failedAt = :ts, errorClass = :ecls, errorMessage = :emsg",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":failed": STATUS_FAILED,
                ":ts": ts,
                ":ecls": err_cls,
                ":emsg": err_msg,
            },
        )
    except Exception as e:
        logger.warning(f"[steps] Failed updating SagaSteps on fail_forward: {e}")

    try:
        runs_table.update_item(
            Key={"sagaId": saga_id},
            UpdateExpression="SET #st = :comp, failedAt = :ts, failedStep = :step, errorName = :ecls",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":comp": STATUS_COMPENSATING,
                ":ts": ts,
                ":step": step_name,
                ":ecls": err_cls,
            },
        )
    except Exception as e:
        logger.warning(f"[steps] Failed updating SagaRuns on fail_forward: {e}")

    emit(
        saga_id,
        STEP_FAILED,
        step=step_name,
        actor=step_name,
        path=path,
        errorClass=err_cls,
        errorMessage=err_msg,
    )


class CompensationStatus(str):
    status: str
    attempt: int

    def __new__(cls, status: str, attempt: int = 1):
        obj = str.__new__(cls, status)
        obj.status = status
        obj.attempt = attempt
        return obj


def begin_compensation(saga_id: str, step_name: str, path: Optional[str] = None) -> CompensationStatus:
    """
    Attempts to transition COMPLETED -> COMPENSATING.
    Increments compInvocations on each call.
    If step is already COMPENSATED or was never COMPLETED, returns CompensationStatus("NOOP", 0).
    If already COMPENSATED, also emits COMP_DUPLICATE_IGNORED (D8).
    Returns CompensationStatus("PROCEED", attempt) if compensation logic should run.
    """
    steps_table = get_table(STEPS_TABLE_NAME)

    # 1. Fetch current step state
    try:
        resp = steps_table.get_item(Key={"sagaId": saga_id, "step": step_name})
    except Exception as e:
        logger.warning(f"[steps] get_item error in begin_compensation: {e}")
        return CompensationStatus("NOOP", 0)

    if "Item" not in resp:
        # Non-completed / non-existent step: compensation returns NOOP (Acceptance b)
        return CompensationStatus("NOOP", 0)

    item = resp["Item"]
    current_status = item.get("status")

    if current_status == STATUS_COMPENSATED:
        # Already compensated: record duplicate attempt and return NOOP
        try:
            steps_table.update_item(
                Key={"sagaId": saga_id, "step": step_name},
                UpdateExpression="ADD compInvocations :one",
                ExpressionAttributeValues={":one": 1},
            )
        except Exception:
            pass
        emit(saga_id, COMP_DUPLICATE_IGNORED, step=step_name, actor=step_name, path=path)
        return CompensationStatus("NOOP", 0)

    if current_status not in (STATUS_COMPLETED, STATUS_COMPENSATING):
        # Only COMPLETED (or already COMPENSATING during retry) may be compensated
        return CompensationStatus("NOOP", 0)

    # 2. Transition COMPLETED -> COMPENSATING and increment compInvocations
    try:
        resp = steps_table.update_item(
            Key={"sagaId": saga_id, "step": step_name},
            UpdateExpression="SET #st = :compensating ADD compInvocations :one",
            ConditionExpression="#st = :completed OR #st = :compensating",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":compensating": STATUS_COMPENSATING,
                ":completed": STATUS_COMPLETED,
                ":one": 1,
            },
            ReturnValues="UPDATED_NEW",
        )
        attempt = int(resp.get("Attributes", {}).get("compInvocations", 1))
        emit(saga_id, COMP_STARTED, step=step_name, actor=step_name, path=path, attempt=attempt)
        return CompensationStatus("PROCEED", attempt)
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # Re-check if it became COMPENSATED in the meantime
            r2 = steps_table.get_item(Key={"sagaId": saga_id, "step": step_name})
            if r2.get("Item", {}).get("status") == STATUS_COMPENSATED:
                emit(saga_id, COMP_DUPLICATE_IGNORED, step=step_name, actor=step_name, path=path)
            return CompensationStatus("NOOP", 0)
        raise


def complete_compensation(
    saga_id: str,
    step_name: str,
    path: Optional[str] = None,
) -> bool:
    """
    Transitions COMPENSATING -> COMPENSATED.
    Increments compApplied exactly once (conditional).
    Returns True if compApplied was incremented, False if already compensated.
    """
    steps_table = get_table(STEPS_TABLE_NAME)
    ts = now_ms()

    try:
        steps_table.update_item(
            Key={"sagaId": saga_id, "step": step_name},
            UpdateExpression=(
                "SET #st = :compensated, compensatedAt = :ts "
                "ADD compApplied :one"
            ),
            ConditionExpression="#st = :compensating",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":compensated": STATUS_COMPENSATED,
                ":compensating": STATUS_COMPENSATING,
                ":ts": ts,
                ":one": 1,
            },
        )
        emit(saga_id, COMP_COMPLETED, step=step_name, actor=step_name, path=path)
        return True
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            emit(saga_id, COMP_DUPLICATE_IGNORED, step=step_name, actor=step_name, path=path)
            return False
        raise
