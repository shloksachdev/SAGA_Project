"""
Purpose: Idempotent deployment of Path A Step Functions state machine.
Phase: Phase 2
"""

import json
import sys
import os
import botocore.exceptions

# Ensure project root in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.aws import get_boto3_client, get_region
from common.workloads import get_workload
from paths.a.build_asl import build_asl

ROLE_ARN = "arn:aws:iam::000000000000:role/SmokeTestRole"
DEFAULT_STATE_MACHINE_NAME = "saga-path-a"


def deploy(
    state_machine_name: str = DEFAULT_STATE_MACHINE_NAME,
    workload_name: str = "order",
    account_id: str = "000000000000",
) -> str:
    sfn = get_boto3_client("stepfunctions")
    region = get_region()
    workload = get_workload(workload_name)

    asl_def = build_asl(workload, region=region, account_id=account_id)
    definition_str = json.dumps(asl_def)
    sm_arn = f"arn:aws:states:{region}:{account_id}:stateMachine:{state_machine_name}"

    try:
        sfn.create_state_machine(
            name=state_machine_name,
            definition=definition_str,
            roleArn=ROLE_ARN,
        )
        print(f"[deploy-path-a] Created state machine {state_machine_name}: {sm_arn}")
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "StateMachineAlreadyExists":
            sfn.update_state_machine(
                stateMachineArn=sm_arn,
                definition=definition_str,
                roleArn=ROLE_ARN,
            )
            print(f"[deploy-path-a] Updated state machine {state_machine_name}: {sm_arn}")
        else:
            raise

    return sm_arn


if __name__ == "__main__":
    deploy()
