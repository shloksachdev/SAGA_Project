def lambda_handler(event, context):
    """
    Notification service. event['action'] picks the forward action
    ('notify') or the compensating action ('unnotify').

    Worth noting for your writeup: a sent notification can't actually be
    un-sent, so 'unnotify' here sends a follow-up correction message
    rather than a true undo. This is a real, common asymmetry in saga
    literature -- not every step has a clean inverse -- and is worth
    naming explicitly rather than glossing over in your Path A/B/D
    comparison.
    """
    action = event.get("action", "notify")
    order_id = event["orderId"]

    if action == "notify":
        return send_notification(order_id, event)
    elif action == "unnotify":
        return send_retraction(order_id, event)
    else:
        raise ValueError(f"Unknown action: {action}")


def send_notification(order_id, event):
    if event.get("simulateFailure"):
        raise Exception("Simulated notification delivery failure")

    print(f"[Notification] Sent confirmation for order {order_id}")
    return {"orderId": order_id, "status": "NOTIFICATION_SENT"}


def send_retraction(order_id, event):
    print(f"[Notification] Sent retraction/correction for order {order_id}")
    return {"orderId": order_id, "status": "NOTIFICATION_RETRACTED"}
