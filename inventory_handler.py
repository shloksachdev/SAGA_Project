"""
Purpose: Inventory microservice handler (D1, D8).
Phase: Phase 1
"""

import os
import time
import boto3
from common.aws import get_endpoint_url, get_region
from common.handler_helper import execute_step

TABLE_NAME = "Orders"


def _get_table():
    dynamodb = boto3.resource(
        "dynamodb",
        endpoint_url=get_endpoint_url(),
        region_name=get_region(),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    )
    return dynamodb.Table(TABLE_NAME)


def reserve_inventory(order_id: str, envelope) -> dict:
    table = _get_table()
    table.update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET #s = :status, inventoryReservedAt = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "INVENTORY_RESERVED", ":ts": int(time.time())},
    )
    print(f"[Inventory] Reserved stock for order {order_id}")
    return {"orderId": order_id, "status": "INVENTORY_RESERVED"}


def release_inventory(order_id: str, envelope) -> dict:
    table = _get_table()
    table.update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET #s = :status, inventoryReleasedAt = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "INVENTORY_RELEASED", ":ts": int(time.time())},
    )
    print(f"[Inventory] Released stock for order {order_id}")
    return {"orderId": order_id, "status": "INVENTORY_RELEASED"}


def lambda_handler(event, context):
    return execute_step(
        event=event,
        context=context,
        step_name="Inventory",
        forward_fn=reserve_inventory,
        compensate_fn=release_inventory,
        forward_status="INVENTORY_RESERVED",
        compensate_status="INVENTORY_RELEASED",
        success_event_name="InventoryReserved",
        failure_event_name="InventoryFailed",
        compensate_event_name="InventoryCompensated",
    )
