"""
Purpose: Execution trigger and completion polling for Path B (pure choreography).
Phase: Phase 3
"""

import logging
import os
import sys
import time
from typing import Optional

# Ensure project root in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.aws import get_table
from common.contracts import (
    SAGA_STARTED,
    STATUS_COMPENSATED,
    STATUS_COMPLETED,
    STATUS_RUNNING,
    SagaEnvelope,
)
from common.events import get_bus_for_path, publish_event
from common.trace import emit, now_ms

logger = logging.getLogger(__name__)

RUNS_TABLE_NAME = "SagaRuns"


def start_saga(
    envelope: SagaEnvelope,
    timeout_sec: int = 60,
    poll_interval: float = 0.5,
) -> str:
    """
    Executes a saga via Path B pure choreography (EventBridge reverse event chain).
    1. Initializes SagaRuns record as RUNNING.
    2. Emits SAGA_STARTED trace event.
    3. Publishes SagaStarted event to saga-bus-b.
    4. Polls SagaRuns until a terminal status (COMPLETED, COMPENSATED, COMPENSATION_FAILED)
       or timeout_sec is reached.
    Returns sagaId.
    """
    saga_id = envelope.sagaId
    envelope.path = "B"
    ts = now_ms()

    # 1. Initialize SagaRuns record
    runs_table = get_table(RUNS_TABLE_NAME)
    runs_table.put_item(
        Item={
            "sagaId": saga_id,
            "path": "B",
            "workload": envelope.workload,
            "runTag": envelope.runTag,
            "status": STATUS_RUNNING,
            "startedAt": ts,
            "stepCounter": 0,
        }
    )

    # 2. Emit SAGA_STARTED trace event
    emit(
        saga_id,
        SAGA_STARTED,
        actor="PathB_Runner",
        path="B",
        workload=envelope.workload,
    )

    # 3. Publish SagaStarted to EventBridge
    bus_name = get_bus_for_path("B")
    detail = envelope.to_dict()
    detail["path"] = "B"
    detail["action"] = "forward"
    detail["step"] = "Start"
    detail["ts"] = ts

    publish_event(
        bus_name=bus_name,
        source="saga.coordinator",
        detail_type="SagaStarted",
        detail=detail,
        saga_id=saga_id,
    )

    # 4. Poll SagaRuns until terminal
    start_time = time.time()
    terminal_statuses = (STATUS_COMPLETED, STATUS_COMPENSATED, "COMPENSATION_FAILED")

    while time.time() - start_time < timeout_sec:
        resp = runs_table.get_item(Key={"sagaId": saga_id})
        item = resp.get("Item")
        if item:
            status = item.get("status")
            if status in terminal_statuses:
                return saga_id
        time.sleep(poll_interval)

    logger.warning(f"[Path B] Saga {saga_id} timed out after {timeout_sec}s")
    return saga_id
