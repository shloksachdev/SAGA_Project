"""
Purpose: Idempotent provisioning of Path C infrastructure (SQS DLQ, EventBridge rule, SFN core).
Phase: Phase 6
"""

import json
import logging
import os
import sys
from typing import Any, Dict, Optional
import botocore.exceptions

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.aws import get_boto3_client, get_region
from paths.c.deploy import DEFAULT_BUS_NAME, DEFAULT_STATE_MACHINE_NAME, deploy as deploy_sfn

logger = logging.getLogger(__name__)

DLQ_QUEUE_NAME = "saga-c-notification-dlq"
EDGE_RULE_NAME = "path-c-edge-notification"


def ensure_dlq(queue_name: str = DLQ_QUEUE_NAME) -> str:
    """Ensures the SQS Dead-Letter Queue exists and returns its ARN."""
    sqs = get_boto3_client("sqs")
    try:
        resp = sqs.create_queue(QueueName=queue_name)
        queue_url = resp["QueueUrl"]
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] in ("QueueAlreadyExists", "QueueNameExists"):
            queue_url = sqs.get_queue_url(QueueName=queue_name)["QueueUrl"]
        else:
            raise

    # Get Queue ARN
    attrs = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["QueueArn"])
    dlq_arn = attrs["Attributes"]["QueueArn"]
    print(f"[provision-path-c] SQS DLQ ready: {queue_name} -> {dlq_arn}")
    return dlq_arn


def deploy_edge_rule(
    bus_name: str = DEFAULT_BUS_NAME,
    dlq_arn: Optional[str] = None,
    account_id: str = "000000000000",
) -> None:
    events = get_boto3_client("events")
    lambda_client = get_boto3_client("lambda")
    region = get_region()

    pattern = {
        "source": ["saga.order"],
        "detail-type": ["OrderCoreCompleted"],
    }

    rule_resp = events.put_rule(
        Name=EDGE_RULE_NAME,
        EventBusName=bus_name,
        EventPattern=json.dumps(pattern),
        State="ENABLED",
        Description="Path C edge rule delivering OrderCoreCompleted to Notification",
    )
    rule_arn = rule_resp["RuleArn"]

    target_arn = f"arn:aws:lambda:{region}:{account_id}:function:Notification"

    target_def: Dict[str, Any] = {
        "Id": "NotificationTarget",
        "Arn": target_arn,
        "InputPath": "$.detail",
        "RetryPolicy": {
            "MaximumRetryAttempts": 2,
            "MaximumEventAgeInSeconds": 3600,
        },
    }
    if dlq_arn:
        target_def["DeadLetterConfig"] = {"Arn": dlq_arn}

    events.put_targets(
        Rule=EDGE_RULE_NAME,
        EventBusName=bus_name,
        Targets=[target_def],
    )
    print(f"[provision-path-c] Edge rule created: {EDGE_RULE_NAME} -> Notification")

    # Add Lambda invoke permission for events.amazonaws.com
    statement_id = f"EventBridgeInvoke_PathC_Notification"
    try:
        lambda_client.add_permission(
            FunctionName="Notification",
            StatementId=statement_id,
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=rule_arn,
        )
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] != "ResourceConflictException":
            logger.warning(f"Failed to add permission for Notification: {e}")


def provision(
    workload_name: str = "order",
    bus_name: str = DEFAULT_BUS_NAME,
    state_machine_name: str = DEFAULT_STATE_MACHINE_NAME,
) -> Dict[str, str]:
    dlq_arn = ensure_dlq()
    sm_arn = deploy_sfn(state_machine_name=state_machine_name, workload_name=workload_name, bus_name=bus_name)
    deploy_edge_rule(bus_name=bus_name, dlq_arn=dlq_arn)
    print("[provision-path-c] Successfully provisioned Path C core and edge resources.")
    return {"dlqArn": dlq_arn, "stateMachineArn": sm_arn}


if __name__ == "__main__":
    provision()
