"""
Purpose: Event parsing, envelope normalization, and EventBridge publishing (D10, §3.4).
Phase: Phase 1
"""

import json
import logging
from typing import Any, Dict, Optional, Tuple
from common.aws import get_boto3_client
from common.contracts import EVENTS_PUT, SagaEnvelope
from common.trace import emit

logger = logging.getLogger(__name__)


def get_bus_for_path(path: str) -> str:
    """Returns dedicated EventBridge bus name for coordination path (D10)."""
    p = (path or "b").lower()
    return f"saga-bus-{p}"


def parse_event(event: Any) -> Tuple[SagaEnvelope, str]:
    """
    Normalizes any input payload into a (SagaEnvelope, action) tuple.
    Transparently supports:
    1. Direct envelope invocation: {"sagaId": "...", "action": "...", ...}
    2. Legacy test payload: {"action": "create", "orderId": "order-123"}
    3. EventBridge wrapped event: {"detail": {...}, "detail-type": "..."}
    """
    if isinstance(event, str):
        try:
            event = json.loads(event)
        except Exception:
            event = {}

    data: Dict[str, Any] = dict(event or {})

    # Check if wrapped in EventBridge event structure
    if "detail" in data and isinstance(data["detail"], dict):
        detail_data = dict(data["detail"])
        # If detail has envelope fields, merge detail into data
        data = detail_data

    # Check if wrapped in envelope key (e.g. from Step Functions task parameters)
    if "envelope" in data and isinstance(data["envelope"], dict):
        env_dict = dict(data["envelope"])
        if "action" in data:
            env_dict["action"] = data["action"]
        data = env_dict

    # Parse into SagaEnvelope
    envelope = SagaEnvelope.from_dict(data)

    # Determine action: explicit in payload, or fallback from step config / default
    action = data.get("action")
    if not action:
        # Check if detail-type maps to an action or fallback
        detail_type = event.get("detail-type", "") if isinstance(event, dict) else ""
        if "cancel" in detail_type.lower() or "refund" in detail_type.lower() or "release" in detail_type.lower() or "unnotify" in detail_type.lower():
            action = "compensate"
        else:
            action = "forward"

    return envelope, action


def publish_event(
    bus_name: str,
    source: str,
    detail_type: str,
    detail: Dict[str, Any],
    saga_id: Optional[str] = None,
) -> None:
    """Publishes an event to the specified EventBridge bus."""
    events_client = get_boto3_client("events")
    payload_str = json.dumps(detail)

    events_client.put_events(
        Entries=[
            {
                "EventBusName": bus_name,
                "Source": source,
                "DetailType": detail_type,
                "Detail": payload_str,
            }
        ]
    )

    if saga_id:
        emit(
            saga_id,
            EVENTS_PUT,
            actor=source,
            bus=bus_name,
            detailType=detail_type,
        )
