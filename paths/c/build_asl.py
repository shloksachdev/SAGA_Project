"""
Purpose: Programmatic ASL state machine generator for Path C (static hybrid).
Phase: Phase 6
Core: Order -> Payment -> Inventory (with Catch -> sequential compensation chain).
Core Complete: SFN putEvents publishes OrderCoreCompleted to saga-bus-c.
"""

from typing import Any, Dict
from common.policy import COMP_INTERVAL_MS, COMP_MAX_ATTEMPTS
from common.workloads import WorkloadConfig, get_workload


def build_asl(
    workload: WorkloadConfig,
    region: str = "us-east-1",
    account_id: str = "000000000000",
    bus_name: str = "saga-bus-c",
) -> Dict[str, Any]:
    """
    Generates Step Functions ASL for Path C static hybrid core.
    Core contains all steps except the edge step (Notification).
    On core completion, publishes OrderCoreCompleted to saga-bus-c.
    On failure, runs sequential compensation chain for completed core steps.
    """
    core_steps = workload.steps[:-1] if len(workload.steps) > 1 else workload.steps
    num_core = len(core_steps)
    if num_core == 0:
        raise ValueError("Workload must contain at least one core step.")

    states: Dict[str, Any] = {}
    first_step_name = f"Forward_{core_steps[0].name}"
    interval_sec = max(1, COMP_INTERVAL_MS // 1000)

    # 1. Forward States
    for i, step in enumerate(core_steps):
        state_name = f"Forward_{step.name}"
        fn_arn = f"arn:aws:lambda:{region}:{account_id}:function:{step.forwardFn}"

        if i < num_core - 1:
            next_state = f"Forward_{core_steps[i+1].name}"
        else:
            next_state = "PublishOrderCoreCompleted"

        if i == 0:
            catch_target = "Compensated"
        else:
            catch_target = f"Compensate_{core_steps[i-1].name}"

        states[state_name] = {
            "Type": "Task",
            "Resource": fn_arn,
            "Parameters": {
                "envelope.$": "$",
                "action": step.forwardAction,
            },
            "ResultPath": "$.lastResult",
            "Next": next_state,
            "Catch": [
                {
                    "ErrorEquals": ["States.ALL"],
                    "ResultPath": "$.error",
                    "Next": catch_target,
                }
            ],
        }

    # 2. PublishOrderCoreCompleted State (SFN -> EventBridge putEvents)
    states["PublishOrderCoreCompleted"] = {
        "Type": "Task",
        "Resource": "arn:aws:states:::events:putEvents",
        "Parameters": {
            "Entries": [
                {
                    "EventBusName": bus_name,
                    "Source": "saga.order",
                    "DetailType": "OrderCoreCompleted",
                    "Detail.$": "$",
                }
            ]
        },
        "ResultPath": "$.putEventsResult",
        "Next": "SagaSuccess",
    }

    # 3. Compensation States (sequential reverse chain for core steps)
    for k in range(num_core - 1, -1, -1):
        step = core_steps[k]
        comp_state_name = f"Compensate_{step.name}"
        fn_arn = f"arn:aws:lambda:{region}:{account_id}:function:{step.compensatorFn}"

        if k > 0:
            next_comp = f"Compensate_{core_steps[k-1].name}"
        else:
            next_comp = "Compensated"

        states[comp_state_name] = {
            "Type": "Task",
            "Resource": fn_arn,
            "Parameters": {
                "envelope.$": "$",
                "action": step.compensateAction,
            },
            "ResultPath": "$.lastResult",
            "Retry": [
                {
                    "ErrorEquals": ["States.ALL"],
                    "IntervalSeconds": interval_sec,
                    "MaxAttempts": COMP_MAX_ATTEMPTS,
                    "BackoffRate": 1.0,
                }
            ],
            "Next": next_comp,
        }

    # 4. Terminal States
    states["SagaSuccess"] = {
        "Type": "Succeed",
    }
    states["Compensated"] = {
        "Type": "Fail",
        "Error": "SagaCompensated",
        "Cause": "Path C core rollback completed in reverse order",
    }

    return {
        "Comment": f"Path C static hybrid core for workload '{workload.name}'",
        "StartAt": first_step_name,
        "States": states,
    }


if __name__ == "__main__":
    import json
    asl = build_asl(get_workload("order"))
    print(json.dumps(asl, indent=2))
