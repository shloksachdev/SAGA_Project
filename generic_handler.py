"""
Purpose: Generic microservice handler parameterized by env STEP_NAME (Phase 7B).
Phase: Phase 7B
"""

import os
from common.handler_helper import execute_step


def generic_forward(order_id: str, envelope) -> dict:
    step_name = os.environ.get("STEP_NAME", "Step")
    return {"orderId": order_id, "status": f"{step_name.upper()}_COMPLETED"}


def generic_compensate(order_id: str, envelope) -> dict:
    step_name = os.environ.get("STEP_NAME", "Step")
    return {"orderId": order_id, "status": f"{step_name.upper()}_COMPENSATED"}


def lambda_handler(event, context):
    step_name = os.environ.get("STEP_NAME", "Step1")
    return execute_step(
        event=event,
        context=context,
        step_name=step_name,
        forward_fn=generic_forward,
        compensate_fn=generic_compensate,
        forward_status=f"{step_name.upper()}_COMPLETED",
        compensate_status=f"{step_name.upper()}_COMPENSATED",
        success_event_name=f"{step_name}Success",
        failure_event_name=f"{step_name}Failed",
        compensate_event_name=f"{step_name}Compensated",
    )
