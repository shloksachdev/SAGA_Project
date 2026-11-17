"""
Purpose: Idempotent provisioning of EventBridge rules and targets for Path B (pure choreography, D9, D10).
Phase: Phase 3
"""

import json
import logging
import os
import sys
from typing import Dict, List, Optional
import botocore.exceptions

# Ensure project root in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.aws import get_boto3_client, get_region
from common.workloads import WorkloadConfig, get_workload

logger = logging.getLogger(__name__)

DEFAULT_BUS_NAME = "saga-bus-b"
DEFAULT_ACCOUNT_ID = "000000000000"

STEP_EVENT_MAP: Dict[str, Dict[str, str]] = {
    "Order": {
        "success": "OrderCreated",
        "failure": "OrderFailed",
        "compensated": "OrderCancelled",
    },
    "Payment": {
        "success": "PaymentCharged",
        "failure": "PaymentFailed",
        "compensated": "PaymentCompensated",
    },
    "Inventory": {
        "success": "InventoryReserved",
        "failure": "InventoryFailed",
        "compensated": "InventoryCompensated",
    },
    "Notification": {
        "success": "NotificationSent",
        "failure": "NotificationFailed",
        "compensated": "NotificationCompensated",
    },
}


def _get_events_for_step(step_name: str) -> Dict[str, str]:
    if step_name in STEP_EVENT_MAP:
        return STEP_EVENT_MAP[step_name]
    return {
        "success": f"{step_name}Success",
        "failure": f"{step_name}Failed",
        "compensated": f"{step_name}Compensated",
    }


def deploy_forward_rules(
    bus_name: str,
    workload: WorkloadConfig,
    prefix: str = "path-b",
    region: Optional[str] = None,
    account_id: str = DEFAULT_ACCOUNT_ID,
) -> List[str]:
    """
    Provisions forward rules on an EventBridge bus:
    Service i subscribes to the success event of Service i-1 (Order subscribes to SagaStarted).
    Returns list of created rule names.
    """
    events = get_boto3_client("events")
    lambda_client = get_boto3_client("lambda")
    reg = region or get_region()

    created_rules: List[str] = []

    for i, step in enumerate(workload.steps):
        rule_name = f"{prefix}-fwd-{step.name.lower()}"
        target_id = f"{prefix}-fwd-target-{step.name.lower()}"
        lambda_arn = f"arn:aws:lambda:{reg}:{account_id}:function:{step.name}"

        if i == 0:
            pattern = {
                "detail-type": ["SagaStarted"],
            }
        else:
            prev_step = workload.steps[i - 1]
            prev_events = _get_events_for_step(prev_step.name)
            pattern = {
                "source": [f"saga.{prev_step.name.lower()}"],
                "detail-type": [prev_events["success"]],
            }

        # 1. Put Rule
        resp = events.put_rule(
            Name=rule_name,
            EventBusName=bus_name,
            EventPattern=json.dumps(pattern),
            State="ENABLED",
            Description=f"Path B forward rule for {step.name}",
        )
        rule_arn = resp.get("RuleArn") or f"arn:aws:events:{reg}:{account_id}:rule/{bus_name}/{rule_name}"

        # 2. Put Target with InputPath: "$.detail"
        events.put_targets(
            Rule=rule_name,
            EventBusName=bus_name,
            Targets=[
                {
                    "Id": target_id,
                    "Arn": lambda_arn,
                    "InputPath": "$.detail",
                }
            ],
        )

        # 3. Add Lambda Invoke Permission
        statement_id = f"eb-{bus_name}-{rule_name}"
        try:
            lambda_client.add_permission(
                FunctionName=step.name,
                StatementId=statement_id,
                Action="lambda:InvokeFunction",
                Principal="events.amazonaws.com",
                SourceArn=rule_arn,
            )
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] not in ("ResourceConflictException", "ResourceInUseException"):
                logger.warning(f"Failed to add permission for {step.name}: {e}")

        created_rules.append(rule_name)
        print(f"  [provision-path-b] Forward rule created: {rule_name} -> {step.name}")

    return created_rules


def deploy_compensation_rules(
    bus_name: str,
    workload: WorkloadConfig,
    prefix: str = "path-b",
    region: Optional[str] = None,
    account_id: str = DEFAULT_ACCOUNT_ID,
) -> List[str]:
    """
    Provisions reverse compensation rules (D9) on an EventBridge bus:
    Service i subscribes to {Step(i+1)Failed, Step(i+1)Compensated}.
    Returns list of created rule names.
    """
    events = get_boto3_client("events")
    lambda_client = get_boto3_client("lambda")
    reg = region or get_region()

    created_rules: List[str] = []
    n = len(workload.steps)

    for i in range(n - 2, -1, -1):
        step = workload.steps[i]
        downstream = workload.steps[i + 1]
        downstream_events = _get_events_for_step(downstream.name)

        rule_name = f"{prefix}-comp-{step.name.lower()}"
        target_id = f"{prefix}-comp-target-{step.name.lower()}"
        lambda_arn = f"arn:aws:lambda:{reg}:{account_id}:function:{step.name}"

        detail_types = [downstream_events["failure"]]
        if downstream_events.get("compensated"):
            detail_types.append(downstream_events["compensated"])

        pattern = {
            "source": [f"saga.{downstream.name.lower()}"],
            "detail-type": detail_types,
        }

        # 1. Put Rule
        resp = events.put_rule(
            Name=rule_name,
            EventBusName=bus_name,
            EventPattern=json.dumps(pattern),
            State="ENABLED",
            Description=f"Path B compensation rule for {step.name} triggered by {downstream.name}",
        )
        rule_arn = resp.get("RuleArn") or f"arn:aws:events:{reg}:{account_id}:rule/{bus_name}/{rule_name}"

        # 2. Put Target with InputPath: "$.detail"
        events.put_targets(
            Rule=rule_name,
            EventBusName=bus_name,
            Targets=[
                {
                    "Id": target_id,
                    "Arn": lambda_arn,
                    "InputPath": "$.detail",
                }
            ],
        )

        # 3. Add Lambda Invoke Permission
        statement_id = f"eb-{bus_name}-{rule_name}"
        try:
            lambda_client.add_permission(
                FunctionName=step.name,
                StatementId=statement_id,
                Action="lambda:InvokeFunction",
                Principal="events.amazonaws.com",
                SourceArn=rule_arn,
            )
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] not in ("ResourceConflictException", "ResourceInUseException"):
                logger.warning(f"Failed to add permission for {step.name}: {e}")

        created_rules.append(rule_name)
        print(f"  [provision-path-b] Compensation rule created: {rule_name} -> {step.name}")

    return created_rules


def deploy(
    bus_name: str = DEFAULT_BUS_NAME,
    workload_name: str = "order",
    account_id: str = DEFAULT_ACCOUNT_ID,
) -> Dict[str, List[str]]:
    """
    Idempotently deploys all forward and compensation rules for Path B.
    """
    events = get_boto3_client("events")
    region = get_region()
    workload = get_workload(workload_name)

    # 1. Ensure bus exists
    try:
        events.create_event_bus(Name=bus_name)
        print(f"[provision-path-b] Created event bus {bus_name}")
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "ResourceAlreadyExistsException":
            pass
        else:
            raise

    # 2. Deploy forward and compensation rules
    fwd_rules = deploy_forward_rules(bus_name, workload, prefix="path-b", region=region, account_id=account_id)
    comp_rules = deploy_compensation_rules(bus_name, workload, prefix="path-b", region=region, account_id=account_id)

    print(f"[provision-path-b] Successfully deployed {len(fwd_rules)} forward and {len(comp_rules)} compensation rules on {bus_name}")
    return {"forward": fwd_rules, "compensation": comp_rules}


if __name__ == "__main__":
    deploy()
