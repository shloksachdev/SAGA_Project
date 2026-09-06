# payment_handler.py

def lambda_handler(event, context):
    """
    Single entry point for the Payment service. event['action'] tells it
    whether to run the forward action or the compensation — this lets one
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

    print(f"[Payment] Charged card for order {order_id}")
    return {"orderId": order_id, "status": "PAYMENT_COMPLETED"}


def refund_card(order_id, event):
    print(f"[Payment] Refunded card for order {order_id}")
    return {"orderId": order_id, "status": "PAYMENT_COMPENSATED"}