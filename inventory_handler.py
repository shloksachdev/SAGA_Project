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

    print(f"[Inventory] Reserved stock for order {order_id}")
    return {"orderId": order_id, "status": "INVENTORY_RESERVED"}


def release_inventory(order_id, event):
    print(f"[Inventory] Released stock for order {order_id}")
    return {"orderId": order_id, "status": "INVENTORY_RELEASED"}
