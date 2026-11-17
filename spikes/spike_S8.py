"""
Purpose: Spike S8 - Verify sfn.get_execution_history returns state-entered events.
Phase: Phase 0
"""

import json
import time
import botocore.exceptions
from spikes.helper import ROLE_ARN, get_client

def run():
    sfn = get_client("stepfunctions")
    sm_name = "SpikeS8StateMachine"
    sm_arn = f"arn:aws:states:us-east-1:000000000000:stateMachine:{sm_name}"

    print("[S8] Testing sfn.get_execution_history for state-entered events...")

    asl_def = {
        "StartAt": "StateOne",
        "States": {
            "StateOne": {
                "Type": "Pass",
                "Result": {"step": 1},
                "Next": "StateTwo",
            },
            "StateTwo": {
                "Type": "Pass",
                "Result": {"step": 2},
                "End": True,
            },
        },
    }

    try:
        sfn.create_state_machine(
            name=sm_name,
            definition=json.dumps(asl_def),
            roleArn=ROLE_ARN,
        )
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "StateMachineAlreadyExists":
            sfn.update_state_machine(stateMachineArn=sm_arn, definition=json.dumps(asl_def))
        else:
            raise

    start_resp = sfn.start_execution(stateMachineArn=sm_arn, input="{}")
    exec_arn = start_resp["executionArn"]

    for _ in range(15):
        time.sleep(1)
        desc = sfn.describe_execution(executionArn=exec_arn)
        if desc["status"] in ("SUCCEEDED", "FAILED", "TIMED_OUT"):
            break

    # Get history
    history = sfn.get_execution_history(executionArn=exec_arn)
    events = history.get("events", [])
    event_types = [ev["type"] for ev in events]
    print(f"[S8] History event types found: {event_types}")

    state_entered_found = any("StateEntered" in ev_type for ev_type in event_types)

    # Cleanup
    try:
        sfn.delete_state_machine(stateMachineArn=sm_arn)
    except Exception:
        pass

    if state_entered_found:
        print("[S8] PASS: sfn.get_execution_history returns state-entered events.")
        return True
    else:
        print("[S8] FAIL: StateEntered events not present in get_execution_history.")
        return False

if __name__ == "__main__":
    success = run()
    exit(0 if success else 1)
