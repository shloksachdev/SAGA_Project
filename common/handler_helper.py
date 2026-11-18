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


def _send_to_dlq(envelope, error):
    try:
        from common.aws import get_boto3_client
        import json
        sqs = get_boto3_client("sqs")
        queue_url = sqs.get_queue_url(QueueName="saga-c-notification-dlq")["QueueUrl"]
        msg_body = {
            "sagaId": envelope.sagaId,
            "path": envelope.path,
            "step": "Notification",
            "error": str(error),
            "envelope": envelope.to_dict(),
        }
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(msg_body),
        )
    except Exception as ex:
        import logging
        logging.getLogger(__name__).warning(f"Failed sending to DLQ: {ex}")


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
        is_forward = action in (step_cfg.forwardAction, "forward", "create", "charge", "reserve", "notify")
        is_compensate = action in (step_cfg.compensateAction, "compensate", "cancel", "refund", "release", "unnotify")
        is_elect = action in ("elect", "participate", "election")

        if is_elect:
            from common.orchestrator import orchestrate_compensation
            from common.election import participate
            return participate(envelope, step_name, runner_fn=orchestrate_compensation)

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
                    detail["action"] = "forward"
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
                    # Path C Notification edge failure: send to SQS DLQ, record NOTIFICATION_DLQ, do NOT rollback core (Spike S7)
                    if envelope.path == "C" and step_name == "Notification":
                        _send_to_dlq(envelope, e)
                        from common.contracts import NOTIFICATION_DLQ
                        emit(
                            envelope.sagaId,
                            NOTIFICATION_DLQ,
                            actor=step_name,
                            path=envelope.path,
                            error=str(e),
                            edgeFailure=True,
                        )
                        try:
                            runs_table = get_table("SagaRuns")
                            runs_table.update_item(
                                Key={"sagaId": envelope.sagaId},
                                UpdateExpression="SET #st = :comp, edgeFailure = :ef, completedAt = :ts",
                                ExpressionAttributeNames={"#st": "status"},
                                ExpressionAttributeValues={
                                    ":comp": STATUS_COMPLETED,
                                    ":ef": True,
                                    ":ts": now_ms(),
                                },
                            )
                        except Exception:
                            pass
                        return {
                            "orderId": order_id,
                            "status": "NOTIFICATION_FAILED",
                            "error": str(e),
                        }

                    bus_name = get_bus_for_path(envelope.path)
                    detail = envelope.to_dict()
                    detail["action"] = "compensate"
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

                    # In B and C, if Order itself fails in forward execution, no prior steps exist to compensate
                    if step_name == "Order" and envelope.path in ("B", "C"):
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

                    # Path D failure triggers election via CompensationNeeded
                    if envelope.path == "D":
                        elect_detail = dict(detail)
                        elect_detail["action"] = "elect"
                        elect_detail["failedStep"] = step_name
                        from common.contracts import COMP_NEEDED_PUBLISHED
                        emit(envelope.sagaId, COMP_NEEDED_PUBLISHED, actor=step_name, path=envelope.path)
                        publish_event(
                            bus_name="saga-bus-d",
                            source=f"saga.{step_name.lower()}",
                            detail_type="CompensationNeeded",
                            detail=elect_detail,
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
            # Compensation retry for B is done inside the handler (Task 4)
            from common.policy import COMP_INTERVAL_MS, COMP_MAX_ATTEMPTS
            max_attempts = COMP_MAX_ATTEMPTS if envelope.path == "B" else attempt

            last_err = None
            for cur_attempt in range(attempt, max_attempts + 1):
                if cur_attempt > attempt:
                    try:
                        steps_table = get_table("SagaSteps")
                        steps_table.update_item(
                            Key={"sagaId": envelope.sagaId, "step": step_name},
                            UpdateExpression="ADD compInvocations :one",
                            ExpressionAttributeValues={":one": 1},
                        )
                    except Exception:
                        pass

                try:
                    apply_faults(envelope, step_name, phase="compensate", attempt=cur_attempt)
                    compensate_fn(order_id, envelope)
                    complete_compensation(envelope.sagaId, step_name, path=envelope.path)
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    from common.contracts import COMP_FAILED_ATTEMPT
                    emit(
                        envelope.sagaId,
                        COMP_FAILED_ATTEMPT,
                        step=step_name,
                        actor=step_name,
                        path=envelope.path,
                        error=str(e),
                        attempt=cur_attempt,
                    )
                    if cur_attempt < max_attempts:
                        import time
                        time.sleep(COMP_INTERVAL_MS / 1000.0)

            if last_err is not None:
                if envelope.path == "B" or (envelope.path == "C" and step_name == "Notification"):
                    from common.contracts import SAGA_COMPENSATION_FAILED
                    emit(
                        envelope.sagaId,
                        SAGA_COMPENSATION_FAILED,
                        step=step_name,
                        actor=step_name,
                        path=envelope.path,
                        error=str(last_err),
                    )
                    try:
                        runs_table = get_table("SagaRuns")
                        runs_table.update_item(
                            Key={"sagaId": envelope.sagaId},
                            UpdateExpression="SET #st = :failed, failedStep = :step, errorName = :err",
                            ExpressionAttributeNames={"#st": "status"},
                            ExpressionAttributeValues={
                                ":failed": "COMPENSATION_FAILED",
                                ":step": step_name,
                                ":err": str(last_err),
                            },
                        )
                    except Exception:
                        pass
                    return {
                        "orderId": order_id,
                        "status": "COMPENSATION_FAILED",
                        "error": str(last_err),
                    }
                raise last_err

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
                detail["action"] = "compensate"
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
