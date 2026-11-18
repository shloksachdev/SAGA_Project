"""
Purpose: Leader election, heartbeat loop, watcher retry, and leader crash fault handling (D7, §4 Phase 4).
Phase: Phase 4
Constraint: No static references to workloads or hard-coded service names (D5).
"""

import logging
import random
import threading
import time
from typing import Any, Callable, Dict, Optional

from common.aws import get_table
from common.contracts import (
    ELECTION_START,
    SAGA_COMPENSATED,
    SAGA_COMPENSATION_FAILED,
    STATUS_COMPENSATED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    WATCHER_RETRY,
    SagaEnvelope,
)
from common.lease import Lease, get_lease, release_done, renew, try_acquire
from common.policy import HEARTBEAT_MS, LEASE_TTL_MS, WATCH_JITTER_MS, WATCH_MAX_ROUNDS
from common.trace import emit, now_ms

logger = logging.getLogger(__name__)


class LeaderContext:
    def __init__(self, lease: Lease, stop_event: threading.Event):
        self.lease = lease
        self.stop_event = stop_event
        self.dispatches_count: int = 0
        self.crashed: bool = False

    def report_dispatch(self) -> None:
        self.dispatches_count += 1


def _start_heartbeat(lease: Lease, stop_event: threading.Event) -> threading.Thread:
    def heartbeat_loop():
        interval_sec = (HEARTBEAT_MS / 1000.0) if HEARTBEAT_MS > 0 else 1.0
        while not stop_event.wait(interval_sec):
            if not renew(lease):
                break

    t = threading.Thread(target=heartbeat_loop, daemon=True)
    t.start()
    return t


def default_trivial_runner(leader_ctx: LeaderContext, envelope: SagaEnvelope) -> None:
    """Trivial compensation runner for Phase 4 (record call, support leader crash)."""
    leader_ctx.report_dispatch()

    # Task 4: leaderFault=crash_after:K support (applies to initial leader epoch 1)
    if leader_ctx.lease.epoch == 1 and envelope.leaderFault and envelope.leaderFault.startswith("crash_after:"):
        try:
            k = int(envelope.leaderFault.split(":")[1])
            if leader_ctx.dispatches_count >= k:
                leader_ctx.crashed = True
                return
        except Exception as e:
            logger.warning(f"Error parsing leaderFault: {e}")

    # Mark SagaRuns as COMPENSATED and emit SAGA_COMPENSATED
    runs_table = get_table("SagaRuns")
    ts = now_ms()
    try:
        runs_table.update_item(
            Key={"sagaId": envelope.sagaId},
            UpdateExpression="SET #st = :comp, compensatedAt = :ts",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":comp": STATUS_COMPENSATED,
                ":ts": ts,
            },
        )
    except Exception as e:
        logger.warning(f"Failed updating SagaRuns on trivial runner complete: {e}")

    emit(envelope.sagaId, SAGA_COMPENSATED, actor=leader_ctx.lease.owner_id, path=envelope.path)


def default_orchestrator_runner(leader_ctx: LeaderContext, envelope: SagaEnvelope) -> None:
    from common.orchestrator import orchestrate_compensation
    orchestrate_compensation(leader_ctx, envelope)


def _run_leader(
    lease: Lease,
    envelope: SagaEnvelope,
    my_step: str,
    runner_fn: Optional[Callable[[LeaderContext, SagaEnvelope], None]] = None,
) -> Dict[str, Any]:
    stop_event = threading.Event()
    leader_ctx = LeaderContext(lease=lease, stop_event=stop_event)
    _start_heartbeat(lease, stop_event)

    runner = runner_fn or default_orchestrator_runner
    try:
        runner(leader_ctx, envelope)
    finally:
        stop_event.set()

    if leader_ctx.crashed:
        # Leader stops heartbeating and returns without releasing lease
        logger.info(f"[election] Leader {my_step} crashed as instructed by leaderFault.")
        return {"role": "LEADER", "status": "CRASHED", "epoch": lease.epoch}

    release_done(lease)
    return {"role": "LEADER", "status": "COMPLETED", "epoch": lease.epoch}


def _run_watcher(
    envelope: SagaEnvelope,
    my_step: str,
    runner_fn: Optional[Callable[[LeaderContext, SagaEnvelope], None]] = None,
) -> Dict[str, Any]:
    runs_table = get_table("SagaRuns")
    terminal_statuses = (STATUS_COMPLETED, STATUS_COMPENSATED, "COMPENSATION_FAILED")

    for round_num in range(1, WATCH_MAX_ROUNDS + 1):
        # 1. Check if saga is already terminal
        try:
            runs_item = runs_table.get_item(Key={"sagaId": envelope.sagaId}).get("Item")
            if runs_item and runs_item.get("status") in terminal_statuses:
                return {"role": "WATCHER", "status": "TERMINAL_OBSERVED", "round": round_num}
        except Exception:
            pass

        # 2. Inspect current lease
        lease_info = get_lease(envelope.sagaId)
        if lease_info and lease_info.get("status") == "DONE":
            return {"role": "WATCHER", "status": "DONE_OBSERVED", "round": round_num}

        expires_at = int(lease_info.get("leaseExpiresAt", now_ms())) if lease_info else now_ms()
        now = now_ms()
        wait_ms = max(0, expires_at - now) + random.randint(0, WATCH_JITTER_MS)
        time.sleep(wait_ms / 1000.0)

        # 3. Check again if terminal before takeover attempt
        try:
            runs_item = runs_table.get_item(Key={"sagaId": envelope.sagaId}).get("Item")
            if runs_item and runs_item.get("status") in terminal_statuses:
                return {"role": "WATCHER", "status": "TERMINAL_OBSERVED", "round": round_num}
        except Exception:
            pass

        # 4. Attempt takeover
        emit(envelope.sagaId, WATCHER_RETRY, actor=my_step, round=round_num, path=envelope.path)
        lease = try_acquire(envelope.sagaId, owner_id=my_step, ttl_ms=LEASE_TTL_MS)
        if lease is not None:
            # Won takeover!
            return _run_leader(lease, envelope, my_step, runner_fn)

    # Exhausted rounds
    emit(envelope.sagaId, SAGA_COMPENSATION_FAILED, actor=my_step, path=envelope.path, error="Watch rounds exhausted")
    try:
        runs_table.update_item(
            Key={"sagaId": envelope.sagaId},
            UpdateExpression="SET #st = :failed, failedStep = :step",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":failed": "COMPENSATION_FAILED",
                ":step": my_step,
            },
        )
    except Exception:
        pass
    return {"role": "WATCHER", "status": "COMPENSATION_FAILED"}


def participate(
    envelope: SagaEnvelope,
    my_step: str,
    runner_fn: Optional[Callable[[LeaderContext, SagaEnvelope], None]] = None,
) -> Dict[str, Any]:
    """
    Candidate entry point for lease election.
    1. A service is a participant only if it has a step record for this saga
       with status COMPLETED, or it is the failed step (STATUS_FAILED).
    2. Non-participants return immediately without acquiring lease or watching.
    3. Winner of try_acquire becomes the leader.
    4. Losers enter watch() loop.
    """
    steps_table = get_table("SagaSteps")

    try:
        resp = steps_table.get_item(Key={"sagaId": envelope.sagaId, "step": my_step})
        item = resp.get("Item")
        if not item:
            return {"role": "NON_PARTICIPANT", "status": "IGNORED"}
        step_status = item.get("status")
        if step_status not in (STATUS_COMPLETED, STATUS_FAILED):
            return {"role": "NON_PARTICIPANT", "status": "IGNORED"}
    except Exception as e:
        logger.warning(f"[election] Error checking participation eligibility for {my_step}: {e}")
        return {"role": "NON_PARTICIPANT", "status": "IGNORED"}

    # Eligible participant
    emit(envelope.sagaId, ELECTION_START, actor=my_step, path=envelope.path)

    lease = try_acquire(envelope.sagaId, owner_id=my_step, ttl_ms=LEASE_TTL_MS)
    if lease is not None:
        return _run_leader(lease, envelope, my_step, runner_fn)
    else:
        return _run_watcher(envelope, my_step, runner_fn)
