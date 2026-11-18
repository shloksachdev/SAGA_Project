"""
Purpose: Execution launcher and polling coordinator for Path C (static hybrid).
Phase: Phase 6
"""

import json
import logging
import os
import sys
import time
from typing import Any, Dict, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.aws import get_boto3_client, get_region, get_table
from common.contracts import (
    SAGA_STARTED,
    STATUS_COMPENSATED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
    SagaEnvelope,
)
from common.trace import emit, now_ms
from paths.c.deploy import DEFAULT_STATE_MACHINE_NAME, deploy
from paths.c.provision import provision

logger = logging.getLogger(__name__)


def start_saga(
    envelope: SagaEnvelope,
    state_machine_arn: Optional[str] = None,
    timeout_sec: int = 60,
    poll_interval: float = 0.5,
) -> str:
    """
    Executes a saga via Path C (Step Functions core + EventBridge edge).
    Writes SAGA_STARTED trace event and initializes SagaRuns record.
    Waits for the saga to reach terminal state in SagaRuns (or timeout).
    Returns the sagaId.
    """
    sfn = get_boto3_client("stepfunctions")
    region = get_region()
    account_id = "000000000000"

    if not state_machine_arn:
        state_machine_arn = f"arn:aws:states:{region}:{account_id}:stateMachine:{DEFAULT_STATE_MACHINE_NAME}"
        try:
            sfn.describe_state_machine(stateMachineArn=state_machine_arn)
        except Exception:
            res = provision(workload_name=envelope.workload)
            state_machine_arn = res["stateMachineArn"]

    saga_id = envelope.sagaId
    ts = now_ms()

    # 1. Initialize SagaRuns record
    runs_table = get_table("SagaRuns")
    runs_table.put_item(
        Item={
            "sagaId": saga_id,
            "path": envelope.path,
            "workload": envelope.workload,
            "runTag": envelope.runTag,
            "status": STATUS_RUNNING,
            "startedAt": ts,
            "stepCounter": 0,
        }
    )

    # 2. Emit SAGA_STARTED trace event
    emit(
        saga_id,
        SAGA_STARTED,
        actor="PathC_Runner",
        path=envelope.path,
        workload=envelope.workload,
        runTag=envelope.runTag,
    )

    # 3. Start SFN execution for core
    input_payload = envelope.to_dict()
    exec_resp = sfn.start_execution(
        stateMachineArn=state_machine_arn,
        input=json.dumps(input_payload),
    )
    exec_arn = exec_resp["executionArn"]

    # 4. Poll SagaRuns until terminal state
    terminal_statuses = (STATUS_COMPLETED, STATUS_COMPENSATED, "COMPENSATION_FAILED", STATUS_FAILED)
    deadline = time.time() + timeout_sec

    while time.time() < deadline:
        try:
            item = runs_table.get_item(Key={"sagaId": saga_id}).get("Item")
            if item:
                cur_status = item.get("status")
                if cur_status in terminal_statuses:
                    return saga_id
        except Exception as e:
            logger.warning(f"[path-c-run] Error polling SagaRuns for {saga_id}: {e}")

        # Check if SFN execution failed without updating SagaRuns
        try:
            desc = sfn.describe_execution(executionArn=exec_arn)
            sfn_status = desc.get("status")
            if sfn_status in ("FAILED", "TIMED_OUT"):
                # If SFN execution ended and SagaRuns is still running, check one more time
                item = runs_table.get_item(Key={"sagaId": saga_id}).get("Item")
                if item and item.get("status") in terminal_statuses:
                    return saga_id
        except Exception:
            pass

        time.sleep(poll_interval)

    raise TimeoutError(f"Path C saga {saga_id} did not reach terminal state within {timeout_sec}s")


if __name__ == "__main__":
    import uuid
    test_envelope = SagaEnvelope(
        sagaId=f"test-c-{uuid.uuid4().hex[:8]}",
        path="C",
        workload="order",
        workScale=0.0,
    )
    sid = start_saga(test_envelope)
    print(f"Path C saga {sid} completed.")
