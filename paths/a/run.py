"""
Purpose: Execution launcher and polling coordinator for Path A (pure orchestration).
Phase: Phase 2
"""

import json
import time
from typing import Optional
from common.aws import get_boto3_client, get_region, get_table
from common.contracts import SAGA_STARTED, STATUS_RUNNING, SagaEnvelope
from common.trace import emit, now_ms
from paths.a.deploy import DEFAULT_STATE_MACHINE_NAME, deploy


def start_saga(
    envelope: SagaEnvelope,
    state_machine_arn: Optional[str] = None,
    timeout_sec: int = 60,
    poll_interval: float = 0.5,
) -> str:
    """
    Executes a saga via Path A Step Functions state machine.
    Writes SAGA_STARTED trace event and initializes SagaRuns record.
    Waits for the state machine to reach a terminal state (or timeout).
    Returns the sagaId.
    """
    sfn = get_boto3_client("stepfunctions")
    region = get_region()
    account_id = "000000000000"

    if not state_machine_arn:
        sm_name = DEFAULT_STATE_MACHINE_NAME if envelope.workload == "order" else f"{DEFAULT_STATE_MACHINE_NAME}-{envelope.workload}"
        state_machine_arn = f"arn:aws:states:{region}:{account_id}:stateMachine:{sm_name}"
        # Ensure deployed
        try:
            sfn.describe_state_machine(stateMachineArn=state_machine_arn)
        except Exception:
            state_machine_arn = deploy(sm_name, workload_name=envelope.workload)

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

    # 2. Emit SAGA_STARTED trace event (Task 3)
    emit(
        saga_id,
        SAGA_STARTED,
        actor="PathA_Runner",
        path=envelope.path,
        workload=envelope.workload,
    )

    # 3. Start execution
    input_payload = envelope.to_dict()
    # Normalize path
    input_payload["path"] = "A"

    exec_resp = sfn.start_execution(
        stateMachineArn=state_machine_arn,
        name=f"saga-a-{saga_id}",
        input=json.dumps(input_payload),
    )
    exec_arn = exec_resp["executionArn"]

    # 4. Poll execution until terminal
    start_time = time.time()
    while time.time() - start_time < timeout_sec:
        desc = sfn.describe_execution(executionArn=exec_arn)
        status = desc.get("status")
        if status in ("SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"):
            break
        time.sleep(poll_interval)

    return saga_id
