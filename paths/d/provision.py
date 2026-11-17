"""
Purpose: Idempotent provisioning of EventBridge rules for Path D (dynamic coordination, D10).
Phase: Phase 4
"""

import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional
import botocore.exceptions

# Ensure project root in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.aws import get_boto3_client, get_region
from common.workloads import WorkloadConfig, get_workload
from paths.b.provision import deploy_forward_rules

logger = logging.getLogger(__name__)

DEFAULT_BUS_NAME = "saga-bus-d"
DEFAULT_ACCOUNT_ID = "000000000000"
ELECTION_RULE_NAME = "path-d-election"


def deploy_election_rule(
    bus_name: str,
    workload: WorkloadConfig,
    rule_name: str = ELECTION_RULE_NAME,
    region: Optional[str] = None,
    account_id: str = DEFAULT_ACCOUNT_ID,
) -> str:
    """
    Creates one rule matching CompensationNeeded that targets ALL services
    in the workload with action=elect (Phase 4 Task 3).
    """
    events = get_boto3_client("events")
    lambda_client = get_boto3_client("lambda")
    reg = region or get_region()

    pattern = {
        "detail-type": ["CompensationNeeded"],
    }

    # 1. Put Rule
    resp = events.put_rule(
        Name=rule_name,
        EventBusName=bus_name,
        EventPattern=json.dumps(pattern),
        State="ENABLED",
        Description="Path D fan-in election rule for CompensationNeeded",
    )
    rule_arn = resp.get("RuleArn") or f"arn:aws:events:{reg}:{account_id}:rule/{bus_name}/{rule_name}"

    # 2. Put targets for all services with action=elect
    targets = []
    for step in workload.steps:
        target_id = f"path-d-elect-{step.name.lower()}"
        lambda_arn = f"arn:aws:lambda:{reg}:{account_id}:function:{step.name}"

        targets.append(
            {
                "Id": target_id,
                "Arn": lambda_arn,
                "InputTransformer": {
                    "InputPathsMap": {"detail": "$.detail"},
                    "InputTemplate": '{"detail": <detail>, "action": "elect"}',
                },
            }
        )

        # Add Lambda invoke permission
        statement_id = f"eb-{bus_name}-{rule_name}-{step.name.lower()}"
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

    events.put_targets(
        Rule=rule_name,
        EventBusName=bus_name,
        Targets=targets,
    )

    print(f"  [provision-path-d] Election rule created: {rule_name} targeting {len(targets)} services")
    return rule_name


def deploy(
    bus_name: str = DEFAULT_BUS_NAME,
    workload_name: str = "order",
    account_id: str = DEFAULT_ACCOUNT_ID,
) -> Dict[str, Any]:
    """
    Idempotently deploys all forward rules and the election rule for Path D.
    """
    events = get_boto3_client("events")
    region = get_region()
    workload = get_workload(workload_name)

    # 1. Ensure bus exists
    try:
        events.create_event_bus(Name=bus_name)
        print(f"[provision-path-d] Created event bus {bus_name}")
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "ResourceAlreadyExistsException":
            pass
        else:
            raise

    # 2. Deploy forward rules (reusing Path B forward rules on saga-bus-d)
    fwd_rules = deploy_forward_rules(bus_name, workload, prefix="path-d", region=region, account_id=account_id)

    # 3. Deploy election fan-in rule
    elect_rule = deploy_election_rule(bus_name, workload, region=region, account_id=account_id)

    print(f"[provision-path-d] Successfully deployed {len(fwd_rules)} forward rules and election rule '{elect_rule}' on {bus_name}")
    return {"forward": fwd_rules, "election": elect_rule}


if __name__ == "__main__":
    deploy()
