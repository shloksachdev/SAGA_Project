"""
Purpose: DynamoDB conditional lease election and heartbeating (D7, §4 Phase 4).
Phase: Phase 4
Constraint: No static references to workloads or hard-coded service names (D5).
"""

from dataclasses import dataclass
import logging
from typing import Any, Dict, Optional
import botocore.exceptions

from common.aws import get_table
from common.contracts import (
    LEASE_ACQUIRED,
    LEASE_LOST,
    LEASE_RENEWED,
    LEASE_TAKEOVER,
)
from common.policy import LEASE_TTL_MS
from common.trace import emit, now_ms

logger = logging.getLogger(__name__)

TABLE_NAME = "SagaLeases"


@dataclass
class Lease:
    saga_id: str
    epoch: int
    owner_id: str
    expires_at: int
    status: str = "ACTIVE"


def try_acquire(
    saga_id: str,
    owner_id: str,
    ttl_ms: int = LEASE_TTL_MS,
) -> Optional[Lease]:
    """
    Attempts to acquire the lease for saga_id using a single conditional UpdateItem.
    Succeeds if:
      - attribute_not_exists(sagaId) OR
      - (leaseExpiresAt < :now AND #status <> :done)
    Returns Lease on win, None on ConditionalCheckFailedException.
    Emits LEASE_ACQUIRED (epoch=1), LEASE_TAKEOVER (epoch>1), or LEASE_LOST.
    """
    table = get_table(TABLE_NAME)
    now = now_ms()
    expires = now + ttl_ms

    try:
        resp = table.update_item(
            Key={"sagaId": saga_id},
            UpdateExpression=(
                "SET ownerId = :owner, leaseExpiresAt = :expires, #st = :active, "
                "epoch = if_not_exists(epoch, :zero) + :one, "
                "electedAt = if_not_exists(electedAt, :now)"
            ),
            ConditionExpression=(
                "attribute_not_exists(sagaId) OR (leaseExpiresAt < :now AND #st <> :done)"
            ),
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":now": now,
                ":expires": expires,
                ":owner": owner_id,
                ":active": "ACTIVE",
                ":done": "DONE",
                ":zero": 0,
                ":one": 1,
            },
            ReturnValues="ALL_NEW",
        )
        attrs = resp["Attributes"]
        epoch = int(attrs["epoch"])

        if epoch == 1:
            emit(saga_id, LEASE_ACQUIRED, actor=owner_id, epoch=epoch, expires=expires)
        else:
            emit(saga_id, LEASE_TAKEOVER, actor=owner_id, epoch=epoch, expires=expires)

        return Lease(
            saga_id=saga_id,
            epoch=epoch,
            owner_id=owner_id,
            expires_at=expires,
            status="ACTIVE",
        )

    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            emit(saga_id, LEASE_LOST, actor=owner_id)
            return None
        logger.error(f"[lease] Error in try_acquire for {saga_id}: {e}")
        raise


def renew(
    lease: Lease,
    ttl_ms: int = LEASE_TTL_MS,
) -> bool:
    """
    Renews the lease conditional on ownerId, epoch matching and status is ACTIVE.
    Emits LEASE_RENEWED on success, LEASE_LOST on failure.
    """
    table = get_table(TABLE_NAME)
    now = now_ms()
    new_expires = now + ttl_ms

    try:
        table.update_item(
            Key={"sagaId": lease.saga_id},
            UpdateExpression="SET leaseExpiresAt = :new_expires",
            ConditionExpression="ownerId = :owner AND epoch = :epoch AND #st = :active",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":owner": lease.owner_id,
                ":epoch": lease.epoch,
                ":active": "ACTIVE",
                ":new_expires": new_expires,
            },
        )
        lease.expires_at = new_expires
        emit(lease.saga_id, LEASE_RENEWED, actor=lease.owner_id, epoch=lease.epoch, expires=new_expires)
        return True

    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            emit(lease.saga_id, LEASE_LOST, actor=lease.owner_id, epoch=lease.epoch)
            return False
        logger.error(f"[lease] Error in renew for {lease.saga_id}: {e}")
        raise


def release_done(lease: Lease) -> bool:
    """
    Marks the lease as DONE, conditional on ownerId and epoch matching.
    A lease with status=DONE cannot be reacquired.
    """
    table = get_table(TABLE_NAME)
    now = now_ms()

    try:
        table.update_item(
            Key={"sagaId": lease.saga_id},
            UpdateExpression="SET #st = :done, completedAt = :now",
            ConditionExpression="ownerId = :owner AND epoch = :epoch",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":owner": lease.owner_id,
                ":epoch": lease.epoch,
                ":done": "DONE",
                ":now": now,
            },
        )
        lease.status = "DONE"
        return True

    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        logger.error(f"[lease] Error in release_done for {lease.saga_id}: {e}")
        raise


def get_lease(saga_id: str) -> Optional[Dict[str, Any]]:
    """Fetches the current lease item from SagaLeases."""
    table = get_table(TABLE_NAME)
    resp = table.get_item(Key={"sagaId": saga_id})
    return resp.get("Item")
