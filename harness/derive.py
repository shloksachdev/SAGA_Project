"""
Purpose: Metric derivation from SagaTrace events per §3.5 (Task 2).
Phase: Phase 8
"""

import os
import sys
from typing import Any, Dict, List, Optional
from boto3.dynamodb.conditions import Key

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.aws import get_table
from common.contracts import (
    COMP_COMPLETED,
    COMP_DISPATCHED,
    COMP_NEEDED_PUBLISHED,
    COMP_STARTED,
    DDB_OPS,
    EVENTS_PUT,
    LAMBDA_END,
    LAMBDA_INVOKE,
    LEASE_ACQUIRED,
    NOTIFICATION_DLQ,
    SAGA_COMPENSATED,
    SAGA_COMPLETED,
    SAGA_STARTED,
    SFN_TRANSITIONS,
    STEP_COMPLETED,
    STEP_FAILED,
    STEP_STARTED,
)


def query_trace_events(saga_id: str) -> List[Dict[str, Any]]:
    """Retrieves all trace events for a given sagaId from SagaTrace DynamoDB table."""
    trace_table = get_table("SagaTrace")
    resp = trace_table.query(KeyConditionExpression=Key("sagaId").eq(saga_id))
    items = resp.get("Items", [])
    items.sort(key=lambda x: (int(x.get("ts", 0)), x.get("sk", "")))
    return items


def derive_metrics(
    trace_events: List[Dict[str, Any]],
    saga_id: Optional[str] = None,
    path: Optional[str] = None,
    workload: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Computes all §3.5 metrics and resource counts from a list of trace event dicts.
    """
    # Sort events chronologically
    events = sorted(trace_events, key=lambda x: int(x.get("ts", 0)))

    # Detect saga metadata if not supplied
    if not saga_id and events:
        saga_id = events[0].get("sagaId")
    if not path and events:
        for e in events:
            if e.get("path"):
                path = e.get("path")
                break
    if not workload and events:
        for e in events:
            if e.get("detail", {}).get("workload"):
                workload = e.get("detail", {}).get("workload")
                break
            if e.get("workload"):
                workload = e.get("workload")
                break

    # Find key event timestamps
    ts_map: Dict[str, List[int]] = {}
    for e in events:
        evt = e.get("event")
        t = int(e.get("ts", 0))
        if evt:
            ts_map.setdefault(evt, []).append(t)

    # 1. happy_latency: SAGA_COMPLETED.ts - SAGA_STARTED.ts
    happy_latency = None
    if SAGA_COMPLETED in ts_map and SAGA_STARTED in ts_map:
        happy_latency = ts_map[SAGA_COMPLETED][-1] - ts_map[SAGA_STARTED][0]

    # 2. compensation_latency: SAGA_COMPENSATED.ts - STEP_FAILED.ts
    compensation_latency = None
    if SAGA_COMPENSATED in ts_map and STEP_FAILED in ts_map:
        compensation_latency = ts_map[SAGA_COMPENSATED][-1] - ts_map[STEP_FAILED][0]

    # 3. election_time (D): LEASE_ACQUIRED.ts - COMP_NEEDED_PUBLISHED.ts (first acquisition)
    election_time = None
    if LEASE_ACQUIRED in ts_map and COMP_NEEDED_PUBLISHED in ts_map:
        election_time = ts_map[LEASE_ACQUIRED][0] - ts_map[COMP_NEEDED_PUBLISHED][0]

    # 4. scheduling_makespan (D): SAGA_COMPENSATED.ts - LEASE_ACQUIRED.ts
    scheduling_makespan = None
    if SAGA_COMPENSATED in ts_map and LEASE_ACQUIRED in ts_map:
        scheduling_makespan = ts_map[SAGA_COMPENSATED][-1] - ts_map[LEASE_ACQUIRED][0]

    # 5. Resource counts
    lambda_invocations = 0
    lambda_duration_ms = 0.0
    eb_events_count = 0
    sfn_transitions_count = 0
    ddb_wru = 0
    ddb_rru = 0
    sqs_requests = 0

    # Explicit trace counts
    for e in events:
        evt = e.get("event")
        detail = e.get("detail", {})

        if evt == LAMBDA_INVOKE:
            lambda_invocations += 1
        elif evt == LAMBDA_END:
            dur = float(detail.get("durationMs", 0.0))
            lambda_duration_ms += dur
        elif evt == EVENTS_PUT:
            eb_events_count += 1
        elif evt == SFN_TRANSITIONS:
            sfn_transitions_count += int(detail.get("transitions", 1))
        elif evt == DDB_OPS:
            op = detail.get("op", "").lower()
            if op in ("put", "update", "delete", "transact_write"):
                ddb_wru += int(detail.get("wru", 1))
            else:
                ddb_rru += int(detail.get("rru", 1))
        elif evt == NOTIFICATION_DLQ:
            sqs_requests += 1

    # Fallback/derivation if explicit metered events are absent
    if lambda_invocations == 0:
        step_starts = len(ts_map.get(STEP_STARTED, []))
        comp_starts = len(ts_map.get(COMP_STARTED, []))
        election_starts = len(ts_map.get("ELECTION_START", []))
        lambda_invocations = step_starts + comp_starts + election_starts

    if sfn_transitions_count == 0 and path in ("A", "C"):
        # Derive SFN transitions from completed states if S8 fallback active
        step_completed_count = len(ts_map.get(STEP_COMPLETED, []))
        comp_completed_count = len(ts_map.get(COMP_COMPLETED, []))
        # Start state + tasks + end state
        sfn_transitions_count = step_completed_count + comp_completed_count + 2

    if eb_events_count == 0 and path in ("B", "D", "C"):
        # Derive EventBridge puts from business event occurrences
        fwd_puts = len(ts_map.get(STEP_COMPLETED, []))
        comp_puts = len(ts_map.get(COMP_NEEDED_PUBLISHED, []))
        eb_events_count = fwd_puts + comp_puts

    # DynamoDB default ops estimation if DDB_OPS unmetered
    if ddb_wru == 0:
        # At least 1 run record + 1 step record per completed step
        ddb_wru = 1 + len(ts_map.get(STEP_COMPLETED, [])) + len(ts_map.get(COMP_COMPLETED, []))
        ddb_rru = 1 + (2 if path == "D" else 0)

    return {
        "sagaId": saga_id,
        "path": path,
        "workload": workload or "order",
        "happy_latency": happy_latency,
        "compensation_latency": compensation_latency,
        "election_time": election_time,
        "scheduling_makespan": scheduling_makespan,
        "lambda_invocations": lambda_invocations,
        "lambda_duration_ms": lambda_duration_ms,
        "eventbridge_events": eb_events_count,
        "step_functions_transitions": sfn_transitions_count,
        "dynamodb_wru": ddb_wru,
        "dynamodb_rru": ddb_rru,
        "sqs_requests": sqs_requests,
    }


def derive_for_saga(saga_id: str) -> Dict[str, Any]:
    """Queries SagaTrace and derives metrics for a saga."""
    events = query_trace_events(saga_id)
    return derive_metrics(events, saga_id=saga_id)
