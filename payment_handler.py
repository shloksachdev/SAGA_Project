"""
Purpose: Payment microservice handler (D1, D8).
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


def charge_card(order_id: str, envelope) -> dict:
    table = _get_table()
    table.update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET #s = :status, paymentCompletedAt = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "PAYMENT_COMPLETED", ":ts": int(time.time())},
    )
    print(f"[Payment] Charged card for order {order_id}")
    return {"orderId": order_id, "status": "PAYMENT_COMPLETED"}


def refund_card(order_id: str, envelope) -> dict:
    table = _get_table()
    table.update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET #s = :status, paymentRefundedAt = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "PAYMENT_COMPENSATED", ":ts": int(time.time())},
    )
    print(f"[Payment] Refunded card for order {order_id}")
    return {"orderId": order_id, "status": "PAYMENT_COMPENSATED"}


def lambda_handler(event, context):
    return execute_step(
        event=event,
        context=context,
        step_name="Payment",
        forward_fn=charge_card,
        compensate_fn=refund_card,
        forward_status="PAYMENT_COMPLETED",
        compensate_status="PAYMENT_COMPENSATED",
        success_event_name="PaymentCharged",
        failure_event_name="PaymentFailed",
        compensate_event_name="PaymentCompensated",
    )
