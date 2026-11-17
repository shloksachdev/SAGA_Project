"""
Purpose: Order microservice handler (D1, D8).
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


def create_order(order_id: str, envelope) -> dict:
    table = _get_table()
    table.put_item(
        Item={
            "orderId": order_id,
            "status": "CREATED",
            "createdAt": int(time.time()),
        }
    )
    print(f"[Order] Created order {order_id} in DynamoDB")
    return {"orderId": order_id, "status": "ORDER_CREATED"}


def cancel_order(order_id: str, envelope) -> dict:
    table = _get_table()
    table.update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET #s = :status, cancelledAt = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "CANCELLED", ":ts": int(time.time())},
    )
    print(f"[Order] Cancelled order {order_id} in DynamoDB")
    return {"orderId": order_id, "status": "ORDER_CANCELLED"}


def lambda_handler(event, context):
    return execute_step(
        event=event,
        context=context,
        step_name="Order",
        forward_fn=create_order,
        compensate_fn=cancel_order,
        forward_status="ORDER_CREATED",
        compensate_status="ORDER_CANCELLED",
        success_event_name="OrderCreated",
        failure_event_name="OrderFailed",
        compensate_event_name="OrderCancelled",
    )
