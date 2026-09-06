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

    print(f"[Order] Created order {order_id}")
    return {"orderId": order_id, "status": "ORDER_CREATED"}


def cancel_order(order_id, event):
    print(f"[Order] Cancelled order {order_id}")
    return {"orderId": order_id, "status": "ORDER_CANCELLED"}
