"""
Purpose: Spike S4 - Verify DynamoDB atomic conditional lease acquisition with epoch increment.
Phase: Phase 0
"""

import time
import botocore.exceptions
from spikes.helper import get_client

def run():
    ddb = get_client("dynamodb")
    table_name = "SpikeS4LeaseTable"

    print("[S4] Setting up table for conditional lease test...")
    try:
        ddb.create_table(
            TableName=table_name,
            AttributeDefinitions=[{"AttributeName": "sagaId", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "sagaId", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] != "ResourceInUseException":
            raise

    saga_id = f"s4-saga-{int(time.time()*1000)}"
    now_ms = int(time.time() * 1000)
    ttl_ms = 5000

    # Step 1: First acquisition should succeed
    print("[S4] Test 1: First acquisition on non-existent item...")
    try:
        ddb.update_item(
            TableName=table_name,
            Key={"sagaId": {"S": saga_id}},
            UpdateExpression="SET ownerId = :owner, leaseExpiresAt = :exp, #status = :act, epoch = if_not_exists(epoch, :zero) + :one, electedAt = :now",
            ConditionExpression="attribute_not_exists(sagaId) OR (leaseExpiresAt < :now AND #status <> :done)",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":owner": {"S": "node-1"},
                ":exp": {"N": str(now_ms + ttl_ms)},
                ":act": {"S": "ACTIVE"},
                ":zero": {"N": "0"},
                ":one": {"N": "1"},
                ":now": {"N": str(now_ms)},
                ":done": {"S": "DONE"},
            },
            ReturnValues="ALL_NEW",
        )
        print("[S4] First acquisition succeeded.")
    except Exception as e:
        print(f"[S4] FAIL on first acquisition: {e}")
        return False

    # Step 2: Second acquisition while active should fail with ConditionalCheckFailedException
    print("[S4] Test 2: Competing acquisition while active (should fail)...")
    competing_failed = False
    try:
        ddb.update_item(
            TableName=table_name,
            Key={"sagaId": {"S": saga_id}},
            UpdateExpression="SET ownerId = :owner, leaseExpiresAt = :exp, #status = :act, epoch = if_not_exists(epoch, :zero) + :one, electedAt = :now",
            ConditionExpression="attribute_not_exists(sagaId) OR (leaseExpiresAt < :now AND #status <> :done)",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":owner": {"S": "node-2"},
                ":exp": {"N": str(now_ms + ttl_ms)},
                ":act": {"S": "ACTIVE"},
                ":zero": {"N": "0"},
                ":one": {"N": "1"},
                ":now": {"N": str(now_ms)},
                ":done": {"S": "DONE"},
            },
        )
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            print("[S4] Competing acquisition failed with ConditionalCheckFailedException as expected.")
            competing_failed = True
        else:
            print(f"[S4] Unexpected error code: {e.response['Error']['Code']}")

    # Step 3: Acquisition after expiry should succeed (takeover) and epoch becomes 2
    print("[S4] Test 3: Takeover after expiry (simulated with future timestamp)...")
    future_now_ms = now_ms + ttl_ms + 1000
    takeover_ok = False
    try:
        resp = ddb.update_item(
            TableName=table_name,
            Key={"sagaId": {"S": saga_id}},
            UpdateExpression="SET ownerId = :owner, leaseExpiresAt = :exp, #status = :act, epoch = if_not_exists(epoch, :zero) + :one, electedAt = :now",
            ConditionExpression="attribute_not_exists(sagaId) OR (leaseExpiresAt < :now AND #status <> :done)",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":owner": {"S": "node-2"},
                ":exp": {"N": str(future_now_ms + ttl_ms)},
                ":act": {"S": "ACTIVE"},
                ":zero": {"N": "0"},
                ":one": {"N": "1"},
                ":now": {"N": str(future_now_ms)},
                ":done": {"S": "DONE"},
            },
            ReturnValues="ALL_NEW",
        )
        new_epoch = int(resp["Attributes"]["epoch"]["N"])
        new_owner = resp["Attributes"]["ownerId"]["S"]
        print(f"[S4] Takeover succeeded: epoch={new_epoch}, owner={new_owner}")
        if new_epoch == 2 and new_owner == "node-2":
            takeover_ok = True
    except Exception as e:
        print(f"[S4] Takeover failed: {e}")

    # Cleanup
    try:
        ddb.delete_table(TableName=table_name)
    except Exception:
        pass

    if competing_failed and takeover_ok:
        print("[S4] PASS: Conditional UpdateItem with epoch increment functions correctly.")
        return True
    else:
        print("[S4] FAIL: Did not satisfy conditional update check.")
        return False

if __name__ == "__main__":
    success = run()
    exit(0 if success else 1)
