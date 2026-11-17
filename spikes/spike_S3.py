"""
Purpose: Spike S3 - Verify Step Functions putEvents service integration.
Phase: Phase 0
"""

import json
import time
import botocore.exceptions
from spikes.helper import ROLE_ARN, get_client

def run():
    sfn = get_client("stepfunctions")
    events = get_client("events")

    bus_name = "saga-bus"
    sm_name = "SpikeS3StateMachine"
    sm_arn = f"arn:aws:states:us-east-1:000000000000:stateMachine:{sm_name}"

    print("[S3] Checking Step Functions putEvents service integration...")
    try:
        events.create_event_bus(Name=bus_name)
    except botocore.exceptions.ClientError:
        pass

    asl_def = {
        "StartAt": "PublishEvent",
        "States": {
            "PublishEvent": {
                "Type": "Task",
                "Resource": "arn:aws:states:::events:putEvents",
                "Parameters": {
                    "Entries": [
                        {
                            "Source": "spike.s3",
                            "DetailType": "Spike3Event",
                            "EventBusName": bus_name,
                            "Detail": json.dumps({"test": "s3_ok"}),
                        }
                    ]
                },
                "End": True,
            }
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

    status = "RUNNING"
    for _ in range(15):
        time.sleep(1)
        desc = sfn.describe_execution(executionArn=exec_arn)
        status = desc["status"]
        if status in ("SUCCEEDED", "FAILED", "TIMED_OUT"):
            break

    # Cleanup
    try:
        sfn.delete_state_machine(stateMachineArn=sm_arn)
    except Exception:
        pass

    if status == "SUCCEEDED":
        print("[S3] PASS: Step Functions putEvents service integration succeeded.")
        return True
    else:
        print(f"[S3] FAIL: Execution ended with status {status}.")
        return False

if __name__ == "__main__":
    success = run()
    exit(0 if success else 1)
