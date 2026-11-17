"""
Purpose: Notification microservice handler (D1, D8).
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


def send_notification(order_id: str, envelope) -> dict:
    table = _get_table()
    table.update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET #s = :status, notificationSentAt = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "NOTIFICATION_SENT", ":ts": int(time.time())},
    )
    print(f"[Notification] Sent confirmation for order {order_id}")
    return {"orderId": order_id, "status": "NOTIFICATION_SENT"}


def send_retraction(order_id: str, envelope) -> dict:
    table = _get_table()
    table.update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET #s = :status, notificationRetractedAt = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "NOTIFICATION_RETRACTED", ":ts": int(time.time())},
    )
    print(f"[Notification] Sent retraction/correction for order {order_id}")
    return {"orderId": order_id, "status": "NOTIFICATION_RETRACTED"}


def lambda_handler(event, context):
    return execute_step(
        event=event,
        context=context,
        step_name="Notification",
        forward_fn=send_notification,
        compensate_fn=send_retraction,
        forward_status="NOTIFICATION_SENT",
        compensate_status="NOTIFICATION_RETRACTED",
        success_event_name="NotificationSent",
        failure_event_name="NotificationFailed",
        compensate_event_name=None,
    )
