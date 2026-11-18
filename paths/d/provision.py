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
    Creates rule(s) matching CompensationNeeded that target ALL services
    in the workload with action=elect (Phase 4 Task 3).
    Splits across multiple rules if targets exceed EventBridge limit of 5.
    """
    events = get_boto3_client("events")
    lambda_client = get_boto3_client("lambda")
    reg = region or get_region()

    pattern = {
        "detail-type": ["CompensationNeeded"],
    }

    base_rule_name = (
        f"path-d-election-{workload.name}"
        if rule_name == ELECTION_RULE_NAME and workload.name not in ("order", "trainticket")
        else rule_name
    )

    targets = []
    for step in workload.steps:
        target_id = f"path-d-elect-{workload.name}-{step.name.lower()}"
        lambda_arn = f"arn:aws:lambda:{reg}:{account_id}:function:{step.name}"

        targets.append(
            {
                "Id": target_id,
                "Arn": lambda_arn,
                "InputTransformer": {
                    "InputPathsMap": {"detail": "$.detail"},
                    "InputTemplate": '{"detail": <detail>, "action": "elect"}',
                },
                "_func_name": step.name,
            }
        )

    chunk_size = 5
    created_rule_names = []

    for chunk_idx in range(0, len(targets), chunk_size):
        chunk = targets[chunk_idx : chunk_idx + chunk_size]
        sub_rule_name = f"{base_rule_name}-{chunk_idx // chunk_size + 1}" if len(targets) > chunk_size else base_rule_name

        resp = events.put_rule(
            Name=sub_rule_name,
            EventBusName=bus_name,
            EventPattern=json.dumps(pattern),
            State="ENABLED",
            Description=f"Path D fan-in election rule for CompensationNeeded ({sub_rule_name})",
        )
        rule_arn = resp.get("RuleArn") or f"arn:aws:events:{reg}:{account_id}:rule/{bus_name}/{sub_rule_name}"

        # Clean existing targets if needed
        try:
            existing = events.list_targets_by_rule(Rule=sub_rule_name, EventBusName=bus_name).get("Targets", [])
            if existing:
                existing_ids = [t["Id"] for t in existing]
                new_ids = {t["Id"] for t in chunk}
                to_remove = [tid for tid in existing_ids if tid not in new_ids]
                if to_remove:
                    events.remove_targets(Rule=sub_rule_name, EventBusName=bus_name, Ids=to_remove)
        except Exception:
            pass

        # Add Lambda invoke permissions
        clean_chunk = []
        for t in chunk:
            func_name = t.pop("_func_name")
            clean_chunk.append(t)
            statement_id = f"eb-{bus_name}-{sub_rule_name}-{func_name.lower()}"
            try:
                lambda_client.add_permission(
                    FunctionName=func_name,
                    StatementId=statement_id,
                    Action="lambda:InvokeFunction",
                    Principal="events.amazonaws.com",
                    SourceArn=rule_arn,
                )
            except botocore.exceptions.ClientError as e:
                if e.response["Error"]["Code"] not in ("ResourceConflictException", "ResourceInUseException"):
                    logger.warning(f"Failed to add permission for {func_name}: {e}")

        events.put_targets(
            Rule=sub_rule_name,
            EventBusName=bus_name,
            Targets=clean_chunk,
        )
        created_rule_names.append(sub_rule_name)
        print(f"  [provision-path-d] Election rule created: {sub_rule_name} targeting {len(clean_chunk)} services")

    return created_rule_names[0] if created_rule_names else base_rule_name


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
