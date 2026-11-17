"""
Purpose: Programmatic ASL state machine definition generator for Path A (pure orchestration).
Phase: Phase 2
"""

from typing import Any, Dict
from common.policy import COMP_INTERVAL_MS, COMP_MAX_ATTEMPTS
from common.workloads import WorkloadConfig, get_workload


def build_asl(
    workload: WorkloadConfig,
    region: str = "us-east-1",
    account_id: str = "000000000000",
) -> Dict[str, Any]:
    """
    Generates Step Functions ASL for pure orchestration (Path A).
    Forward: Step_0 -> Step_1 -> ... -> Step_N -> Succeed.
    Catch: Each forward task routes on States.ALL to the reverse compensation chain
           for steps completed before it.
    Retry: Compensation tasks retry per common/policy.py.
    Terminal: Chain ends in Fail state 'Compensated'.
    """
    steps = workload.steps
    num_steps = len(steps)
    if num_steps == 0:
        raise ValueError("Workload must contain at least one step.")

    states: Dict[str, Any] = {}
    first_step_name = f"Forward_{steps[0].name}"

    interval_sec = max(1, COMP_INTERVAL_MS // 1000)

    # 1. Forward States
    for i, step in enumerate(steps):
        state_name = f"Forward_{step.name}"
        fn_arn = f"arn:aws:lambda:{region}:{account_id}:function:{step.forwardFn}"

        # Determine next forward state
        if i < num_steps - 1:
            next_state = f"Forward_{steps[i+1].name}"
            is_end = False
        else:
            next_state = "SagaSuccess"
            is_end = False

        # Determine catch target (the step completed immediately prior)
        if i == 0:
            catch_target = "Compensated"
        else:
            catch_target = f"Compensate_{steps[i-1].name}"

        forward_task: Dict[str, Any] = {
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
        states[state_name] = forward_task

    # 2. Compensation States (sequential reverse chain)
    # The last step (e.g. Notification) does not need a compensation task if nothing runs after it,
    # but we generate compensation tasks for all steps that can be compensated.
    for k in range(num_steps - 1, -1, -1):
        step = steps[k]
        comp_state_name = f"Compensate_{step.name}"
        fn_arn = f"arn:aws:lambda:{region}:{account_id}:function:{step.compensatorFn}"

        if k > 0:
            next_comp = f"Compensate_{steps[k-1].name}"
        else:
            next_comp = "Compensated"

        comp_task: Dict[str, Any] = {
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
        states[comp_state_name] = comp_task

    # 3. Terminal States
    states["SagaSuccess"] = {
        "Type": "Succeed",
    }
    states["Compensated"] = {
        "Type": "Fail",
        "Error": "SagaCompensated",
        "Cause": "Saga rollback completed in reverse order",
    }

    return {
        "Comment": f"Path A pure orchestration for workload '{workload.name}'",
        "StartAt": first_step_name,
        "States": states,
    }


if __name__ == "__main__":
    import json
    asl = build_asl(get_workload("order"))
    print(json.dumps(asl, indent=2))
