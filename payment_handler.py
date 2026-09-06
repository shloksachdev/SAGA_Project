import os
import time

import boto3

TABLE_NAME = "Orders"

# See order_handler.py for why endpoint_url comes from AWS_ENDPOINT_URL rather
# than being hardcoded to localhost.
dynamodb = boto3.resource(
    "dynamodb",
    endpoint_url=os.environ.get("AWS_ENDPOINT_URL"),
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
)
table = dynamodb.Table(TABLE_NAME)


def lambda_handler(event, context):
    """
    Single entry point for the Payment service. event['action'] tells it
    whether to run the forward action or the compensation -- this lets one
    deployed Lambda serve both the Task and the Compensate-Task in your
    Step Functions ASL (or both event types in Path B).
    """
    action = event.get("action", "charge")
    order_id = event["orderId"]

    if action == "charge":
        return charge_card(order_id, event)
    elif action == "compensate":
        return refund_card(order_id, event)
    else:
        raise ValueError(f"Unknown action: {action}")


def charge_card(order_id, event):
    if event.get("simulateFailure"):
        raise Exception("Simulated payment failure")

    table.update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET #s = :status, paymentCompletedAt = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "PAYMENT_COMPLETED", ":ts": int(time.time())},
    )

    print(f"[Payment] Charged card for order {order_id}")
    return {"orderId": order_id, "status": "PAYMENT_COMPLETED"}


def refund_card(order_id, event):
    table.update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET #s = :status, paymentRefundedAt = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "PAYMENT_COMPENSATED", ":ts": int(time.time())},
    )

    print(f"[Payment] Refunded card for order {order_id}")
    return {"orderId": order_id, "status": "PAYMENT_COMPENSATED"}
