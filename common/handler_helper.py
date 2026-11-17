"""
Purpose: Standardized execution engine for service Lambda handlers (D1, D8, D13).
Phase: Phase 1
"""

from typing import Any, Callable, Dict, Optional
from common.contracts import SAGA_COMPENSATED, SAGA_COMPLETED, STATUS_COMPENSATED, STATUS_COMPLETED
from common.events import get_bus_for_path, parse_event, publish_event
from common.metered import metered_invocation
from common.steps import (
    begin_compensation,
    begin_forward,
    complete_compensation,
    complete_forward,
    fail_forward,
)
from common.trace import emit, now_ms
from common.work import apply_faults, do_work
from common.workloads import get_workload
from common.aws import get_table


def execute_step(
    event: Any,
    context: Any,
    step_name: str,
    forward_fn: Callable[[str, Any], Any],
    compensate_fn: Callable[[str, Any], Any],
    forward_status: str,
    compensate_status: str,
    success_event_name: Optional[str] = None,
    failure_event_name: Optional[str] = None,
    compensate_event_name: Optional[str] = None,
) -> Dict[str, Any]:
    envelope, action = parse_event(event)
    order_id = envelope.orderId or envelope.sagaId

    wl = get_workload(envelope.workload)
    step_cfg = wl.get_step(step_name)
    if not step_cfg:
        raise ValueError(f"Step {step_name} not found in workload {envelope.workload}")

    with metered_invocation(envelope.sagaId, actor=step_name, path=envelope.path):
        is_forward = action in (step_cfg.forwardAction, "forward", "create")
        is_compensate = action in (step_cfg.compensateAction, "compensate", "cancel")

        if is_forward:
            # 1. Idempotent forward start
            res = begin_forward(envelope.sagaId, step_name, path=envelope.path)
            if res == "ALREADY_DONE":
                return {"orderId": order_id, "status": forward_status}

            # 2. Simulated work time
            do_work(step_cfg.forwardMs, step_cfg.jitterMs, envelope.workScale)

            # 3. Execution & Fault Injection
            try:
                apply_faults(envelope, step_name, phase="forward")
                forward_fn(order_id, envelope)
                complete_forward(
                    envelope.sagaId,
                    step_name,
                    step_cfg,
                    path=envelope.path,
                    order_id=order_id,
                )

                # If final forward step, mark saga complete
                if step_name == "Notification":
                    emit(envelope.sagaId, SAGA_COMPLETED, actor=step_name, path=envelope.path)
                    try:
                        runs_table = get_table("SagaRuns")
                        runs_table.update_item(
                            Key={"sagaId": envelope.sagaId},
                            UpdateExpression="SET #st = :comp, completedAt = :ts",
                            ExpressionAttributeNames={"#st": "status"},
                            ExpressionAttributeValues={
                                ":comp": STATUS_COMPLETED,
                                ":ts": now_ms(),
                            },
                        )
                    except Exception:
                        pass

                # Publish success event for event-driven paths (B, D, C-edge)
                should_publish = envelope.path in ("B", "D") or (
                    envelope.path == "C" and step_name == "Notification"
                )
                if should_publish and success_event_name:
                    bus_name = get_bus_for_path(envelope.path)
                    detail = envelope.to_dict()
                    detail["step"] = step_name
                    detail["result"] = forward_status
                    detail["ts"] = now_ms()
                    publish_event(
                        bus_name=bus_name,
                        source=f"saga.{step_name.lower()}",
                        detail_type=success_event_name,
                        detail=detail,
                        saga_id=envelope.sagaId,
                    )

                return {"orderId": order_id, "status": forward_status}

            except Exception as e:
                fail_forward(envelope.sagaId, step_name, e, path=envelope.path)

                # Business failure handling per path (D13)
                is_event_driven = envelope.path in ("B", "D") or (
                    envelope.path == "C" and step_name == "Notification"
                )
                if is_event_driven:
                    bus_name = get_bus_for_path(envelope.path)
                    detail = envelope.to_dict()
                    detail["step"] = step_name
                    detail["error"] = str(e)
                    detail["ts"] = now_ms()

                    if failure_event_name:
                        publish_event(
                            bus_name=bus_name,
                            source=f"saga.{step_name.lower()}",
                            detail_type=failure_event_name,
                            detail=detail,
                            saga_id=envelope.sagaId,
                        )

                    # Path D failure triggers election via CompensationNeeded
                    if envelope.path == "D":
                        detail["failedStep"] = step_name
                        publish_event(
                            bus_name="saga-bus-d",
                            source=f"saga.{step_name.lower()}",
                            detail_type="CompensationNeeded",
                            detail=detail,
                            saga_id=envelope.sagaId,
                        )

                    return {
                        "orderId": order_id,
                        "status": f"{step_name.upper()}_FAILED",
                        "error": str(e),
                    }
                else:
                    # Step Functions paths (A, C-core): raise to trigger SFN Catch
                    raise e

        elif is_compensate:
            # 1. Idempotent compensation start
            status = begin_compensation(envelope.sagaId, step_name, path=envelope.path)
            if status == "NOOP":
                return {"orderId": order_id, "status": compensate_status}

            # 2. Simulated work time
            do_work(step_cfg.compensateMs, step_cfg.jitterMs, envelope.workScale)

            # 3. Execution & Fault Injection
            attempt = getattr(status, "attempt", 1)
            try:
                apply_faults(envelope, step_name, phase="compensate", attempt=attempt)
                compensate_fn(order_id, envelope)
                complete_compensation(envelope.sagaId, step_name, path=envelope.path)
            except Exception as e:
                from common.contracts import COMP_FAILED_ATTEMPT
                emit(
                    envelope.sagaId,
                    COMP_FAILED_ATTEMPT,
                    step=step_name,
                    actor=step_name,
                    path=envelope.path,
                    error=str(e),
                    attempt=attempt,
                )
                raise e

            # In A, B, and C, the final compensating step is Order cancel (D9, §3.3)
            if step_name == "Order" and envelope.path in ("A", "B", "C"):
                emit(envelope.sagaId, SAGA_COMPENSATED, actor=step_name, path=envelope.path)
                try:
                    runs_table = get_table("SagaRuns")
                    runs_table.update_item(
                        Key={"sagaId": envelope.sagaId},
                        UpdateExpression="SET #st = :comp, compensatedAt = :ts",
                        ExpressionAttributeNames={"#st": "status"},
                        ExpressionAttributeValues={
                            ":comp": STATUS_COMPENSATED,
                            ":ts": now_ms(),
                        },
                    )
                except Exception:
                    pass

            # Path B reverse event chain: publish Compensated event
            if envelope.path == "B" and compensate_event_name:
                bus_name = get_bus_for_path(envelope.path)
                detail = envelope.to_dict()
                detail["step"] = step_name
                detail["result"] = compensate_status
                detail["ts"] = now_ms()
                publish_event(
                    bus_name=bus_name,
                    source=f"saga.{step_name.lower()}",
                    detail_type=compensate_event_name,
                    detail=detail,
                    saga_id=envelope.sagaId,
                )

            return {"orderId": order_id, "status": compensate_status}

        else:
            raise ValueError(f"Unknown action: {action} for step {step_name}")
