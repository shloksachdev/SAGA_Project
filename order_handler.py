import os
import time

import boto3

TABLE_NAME = "Orders"

# Do NOT hardcode endpoint_url="http://localhost:4566" here -- from inside the
# Lambda's own execution environment, "localhost" doesn't route back to the
# LocalStack gateway. LocalStack automatically injects AWS_ENDPOINT_URL into
# every Lambda's environment specifically so SDK clients can find it correctly.
dynamodb = boto3.resource(
    "dynamodb",
    endpoint_url=os.environ.get("AWS_ENDPOINT_URL"),
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
)
table = dynamodb.Table(TABLE_NAME)


def lambda_handler(event, context):
    """
    Order service. event['action'] picks the forward action ('create') or
    the compensating action ('cancel'). Same one-Lambda-both-directions
    shape as the Payment handler.
    """
    action = event.get("action", "create")
    order_id = event["orderId"]

    if action == "create":
        return create_order(order_id, event)
    elif action == "cancel":
        return cancel_order(order_id, event)
    else:
        raise ValueError(f"Unknown action: {action}")


def create_order(order_id, event):
    if event.get("simulateFailure"):
        raise Exception("Simulated order creation failure")

    table.put_item(Item={
        "orderId": order_id,
        "status": "CREATED",
        "createdAt": int(time.time()),
    })

    print(f"[Order] Created order {order_id} in DynamoDB")
    return {"orderId": order_id, "status": "ORDER_CREATED"}


def cancel_order(order_id, event):
    # "status" is a DynamoDB reserved word, so it needs an ExpressionAttributeName
    # alias rather than being used directly in the UpdateExpression.
    table.update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET #s = :status, cancelledAt = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "CANCELLED", ":ts": int(time.time())},
    )

    print(f"[Order] Cancelled order {order_id} in DynamoDB")
    return {"orderId": order_id, "status": "ORDER_CANCELLED"}