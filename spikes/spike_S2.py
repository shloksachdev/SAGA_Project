"""
Purpose: Spike S2 - Verify Step Functions -> Lambda with named-error Catch and Retry (IntervalSeconds 1).
Phase: Phase 0
"""

import json
import time
import botocore.exceptions
from spikes.helper import ROLE_ARN, create_zip_bytes, get_client

def run():
    sfn = get_client("stepfunctions")
    lambda_client = get_client("lambda")

    fn_name = "SpikeS2Lambda"
    sm_name = "SpikeS2StateMachine"

    print("[S2] Setting up Lambda and State Machine...")
    handler_code = """
class CustomBusinessError(Exception):
    pass

def lambda_handler(event, context):
    raise CustomBusinessError("Business logic failure")
"""
    zip_bytes = create_zip_bytes({"spike_s2_handler.py": handler_code})
    try:
        lambda_client.get_function(FunctionName=fn_name)
        lambda_client.update_function_code(FunctionName=fn_name, ZipFile=zip_bytes)
    except botocore.exceptions.ClientError:
        lambda_client.create_function(
            FunctionName=fn_name,
            Runtime="python3.12",
            Role=ROLE_ARN,
            Handler="spike_s2_handler.lambda_handler",
            Code={"ZipFile": zip_bytes},
            Timeout=10,
        )

    fn_arn = f"arn:aws:lambda:us-east-1:000000000000:function:{fn_name}"

    asl_def = {
        "StartAt": "InvokeStep",
        "States": {
            "InvokeStep": {
                "Type": "Task",
                "Resource": fn_arn,
                "Retry": [
                    {
                        "ErrorEquals": ["CustomBusinessError"],
                        "IntervalSeconds": 1,
                        "MaxAttempts": 2,
                        "BackoffRate": 1.0,
                    }
                ],
                "Catch": [
                    {
                        "ErrorEquals": ["CustomBusinessError"],
                        "Next": "CaughtNamedError",
                    },
                    {
                        "ErrorEquals": ["States.ALL"],
                        "Next": "CaughtStatesAll",
                    },
                ],
                "End": True,
            },
            "CaughtNamedError": {
                "Type": "Pass",
                "Result": {"outcome": "CAUGHT_NAMED"},
                "End": True,
            },
            "CaughtStatesAll": {
                "Type": "Pass",
                "Result": {"outcome": "CAUGHT_ALL"},
                "End": True,
            },
        },
    }

    sm_arn = f"arn:aws:states:us-east-1:000000000000:stateMachine:{sm_name}"
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

    # Execute
    start_resp = sfn.start_execution(stateMachineArn=sm_arn, input="{}")
    exec_arn = start_resp["executionArn"]

    # Poll execution
    status = "RUNNING"
    output = None
    for _ in range(20):
        time.sleep(1)
        desc = sfn.describe_execution(executionArn=exec_arn)
        status = desc["status"]
        if status in ("SUCCEEDED", "FAILED", "TIMED_OUT"):
            output = desc.get("output")
            break

    print(f"[S2] Execution status: {status}, output: {output}")

    # Cleanup
    try:
        sfn.delete_state_machine(stateMachineArn=sm_arn)
        lambda_client.delete_function(FunctionName=fn_name)
    except Exception:
        pass

    if status == "SUCCEEDED" and output and "CAUGHT_NAMED" in output:
        print("[S2] PASS: Step Functions caught named error 'CustomBusinessError' and honored Retry/Catch.")
        return True
    elif status == "SUCCEEDED" and output and "CAUGHT_ALL" in output:
        print("[S2] PARTIAL/FALLBACK: Caught States.ALL instead of named error. Use Catch States.ALL fallback.")
        return False
    else:
        print(f"[S2] FAIL: State machine ended with {status}.")
        return False

if __name__ == "__main__":
    success = run()
    exit(0 if success else 1)
