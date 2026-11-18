"""
Purpose: Temporary saga orchestrator adapter for elected leader (D5, §4 Phase 5).
Phase: Phase 5
Constraint: No static references to workloads or hard-coded service names (D5).
"""

import json
import logging
import threading
from typing import Any, Dict, Optional

from boto3.dynamodb.conditions import Key

from common.aws import get_boto3_client, get_table
from common.contracts import (
    COMP_DISPATCHED,
    SAGA_COMPENSATED,
    SAGA_COMPENSATION_FAILED,
    STATUS_COMPENSATED,
    STATUS_COMPENSATION_FAILED,
    SagaEnvelope,
)
from common.core.dag import Node, build_compensation_graph
from common.core.scheduler import run_lifo, run_parallel
from common.election import LeaderContext
from common.lease import release_done
from common.trace import emit, now_ms

logger = logging.getLogger(__name__)


def orchestrate_compensation(leader_ctx: LeaderContext, envelope: SagaEnvelope) -> None:
    """
    Elected leader compensation runner:
    1. Reads step records from SagaSteps table for envelope.sagaId.
    2. Builds the compensation dependency DAG dynamically (D5).
    3. Runs either parallel DAG scheduler or sequential LIFO ablation.
    4. Emits trace events and transitions SagaRuns to COMPENSATED or COMPENSATION_FAILED.
    5. Releases the lease as DONE.
    """
    saga_id = envelope.sagaId
    steps_table = get_table("SagaSteps")
    runs_table = get_table("SagaRuns")

    # 1. Fetch all step records for this saga
    try:
        resp = steps_table.query(KeyConditionExpression=Key("sagaId").eq(saga_id))
        step_records = resp.get("Items", [])
    except Exception as e:
        logger.error(f"[orchestrator] Failed querying SagaSteps for {saga_id}: {e}")
        step_records = []

    # 2. Inspect failed step if any
    failed_step: Optional[str] = None
    try:
        run_resp = runs_table.get_item(Key={"sagaId": saga_id})
        run_item = run_resp.get("Item", {})
        failed_step = run_item.get("failedStep")
    except Exception as e:
        logger.warning(f"[orchestrator] Failed reading SagaRuns for {saga_id}: {e}")

    # 3. Build compensation graph
    graph = build_compensation_graph(step_records, failed_step=failed_step)
    if not graph.nodes:
        # All steps already compensated or none need compensation
        ts = now_ms()
        try:
            runs_table.update_item(
                Key={"sagaId": saga_id},
                UpdateExpression="SET #st = :comp, compensatedAt = :ts",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={
                    ":comp": STATUS_COMPENSATED,
                    ":ts": ts,
                },
            )
        except Exception:
            pass
        emit(saga_id, SAGA_COMPENSATED, actor=leader_ctx.lease.owner_id, path=envelope.path)
        release_done(leader_ctx.lease)
        return

    lambda_client = get_boto3_client("lambda")
    dispatch_lock = threading.Lock()

    def exec_fn(node: Node) -> None:
        if leader_ctx.crashed:
            raise RuntimeError("Leader aborted due to simulated fault")

        with dispatch_lock:
            leader_ctx.report_dispatch()
            # Task 4: leaderFault=crash_after:K support on initial leader (epoch 1)
            if leader_ctx.lease.epoch == 1 and envelope.leaderFault and envelope.leaderFault.startswith("crash_after:"):
                try:
                    k = int(envelope.leaderFault.split(":")[1])
                    if leader_ctx.dispatches_count > k:
                        leader_ctx.crashed = True
                        leader_ctx.stop_event.set()
                        raise RuntimeError("Leader stopped per leaderFault crash simulation")
                except ValueError:
                    pass

        # Emit COMP_DISPATCHED trace event
        emit(
            saga_id,
            COMP_DISPATCHED,
            step=node.step,
            actor=leader_ctx.lease.owner_id,
            path=envelope.path,
        )

        fn_name = node.compensatorFn or node.step
        action = node.compensateAction or "compensate"

        payload_dict = {
            "action": action,
            "saga": envelope.to_dict(),
            "step": node.step,
        }

        resp = lambda_client.invoke(
            FunctionName=fn_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload_dict).encode("utf-8"),
        )

        if "FunctionError" in resp:
            err_payload = resp.get("Payload")
            err_text = err_payload.read().decode("utf-8") if err_payload else "FunctionError"
            raise RuntimeError(f"Lambda invocation {fn_name} returned error: {err_text}")

        resp_payload = resp.get("Payload")
        if resp_payload:
            try:
                body = json.loads(resp_payload.read().decode("utf-8"))
                if isinstance(body, dict) and body.get("status") == STATUS_COMPENSATION_FAILED:
                    raise RuntimeError(f"Step {node.step} returned failure: {body.get('error')}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

    # 4. Execute using chosen compMode (parallel DAG vs sequential LIFO)
    if envelope.compMode == "lifo":
        outcome = run_lifo(graph, exec_fn)
    else:
        outcome = run_parallel(graph, exec_fn, max_workers=8)

    if leader_ctx.crashed:
        # Leader stopped heartbeating and exits without release_done (enables watcher takeover)
        logger.info(f"[orchestrator] Leader {leader_ctx.lease.owner_id} crashed after {leader_ctx.dispatches_count} dispatches.")
        return

    ts = now_ms()
    if outcome == STATUS_COMPENSATED:
        try:
            runs_table.update_item(
                Key={"sagaId": saga_id},
                UpdateExpression="SET #st = :comp, compensatedAt = :ts",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={
                    ":comp": STATUS_COMPENSATED,
                    ":ts": ts,
                },
            )
        except Exception as e:
            logger.warning(f"[orchestrator] Failed updating SagaRuns on completion: {e}")
        emit(saga_id, SAGA_COMPENSATED, actor=leader_ctx.lease.owner_id, path=envelope.path)
        release_done(leader_ctx.lease)
    else:
        try:
            runs_table.update_item(
                Key={"sagaId": saga_id},
                UpdateExpression="SET #st = :failed",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={":failed": STATUS_COMPENSATION_FAILED},
            )
        except Exception as e:
            logger.warning(f"[orchestrator] Failed updating SagaRuns on failure: {e}")
        emit(saga_id, SAGA_COMPENSATION_FAILED, actor=leader_ctx.lease.owner_id, path=envelope.path)
        release_done(leader_ctx.lease)
