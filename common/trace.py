"""
Purpose: Append-only distributed tracing into SagaTrace table (D3).
Phase: Phase 1
"""

import logging
import os
import time
import uuid
from typing import Any, Dict, Optional
import botocore.exceptions
from common.aws import get_endpoint_url, get_region
from common.contracts import ALL_TRACE_EVENTS
import boto3

logger = logging.getLogger(__name__)

TRACE_TABLE_NAME = "SagaTrace"


def now_ms() -> int:
    """Returns epoch milliseconds from system nanoseconds (D15)."""
    return time.time_ns() // 1_000_000


def emit(
    saga_id: str,
    event: str,
    step: Optional[str] = None,
    actor: Optional[str] = None,
    path: Optional[str] = None,
    **detail: Any,
) -> None:
    """
    Appends an immutable event row to SagaTrace.
    Never raises an exception — trace failure must never abort business execution.
    """
    try:
        ts = now_ms()
        sk = f"{ts:014d}#{uuid.uuid4().hex[:6]}"

        item: Dict[str, Any] = {
            "sagaId": saga_id,
            "sk": sk,
            "event": event,
            "ts": ts,
            "detail": detail,
        }
        if step:
            item["step"] = step
        if actor:
            item["actor"] = actor
        if path:
            item["path"] = path
        if "epoch" in detail:
            item["epoch"] = detail["epoch"]

        dynamodb = boto3.resource(
            "dynamodb",
            endpoint_url=get_endpoint_url(),
            region_name=get_region(),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
        )
        table = dynamodb.Table(TRACE_TABLE_NAME)
        table.put_item(Item=item)
    except Exception as e:
        logger.warning(f"[trace] Failed to emit trace event {event} for saga {saga_id}: {e}")
