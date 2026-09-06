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
    Inventory service. event['action'] picks the forward action ('reserve')
    or the compensating action ('release').
    """
    action = event.get("action", "reserve")
    order_id = event["orderId"]

    if action == "reserve":
        return reserve_inventory(order_id, event)
    elif action == "release":
        return release_inventory(order_id, event)
    else:
        raise ValueError(f"Unknown action: {action}")


def reserve_inventory(order_id, event):
    if event.get("simulateFailure"):
        raise Exception("Simulated inventory shortage")

    table.update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET #s = :status, inventoryReservedAt = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "INVENTORY_RESERVED", ":ts": int(time.time())},
    )

    print(f"[Inventory] Reserved stock for order {order_id}")
    return {"orderId": order_id, "status": "INVENTORY_RESERVED"}


def release_inventory(order_id, event):
    table.update_item(
        Key={"orderId": order_id},
        UpdateExpression="SET #s = :status, inventoryReleasedAt = :ts",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":status": "INVENTORY_RELEASED", ":ts": int(time.time())},
    )

    print(f"[Inventory] Released stock for order {order_id}")
    return {"orderId": order_id, "status": "INVENTORY_RELEASED"}
