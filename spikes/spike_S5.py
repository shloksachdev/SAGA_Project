"""
Purpose: Spike S5 - Verify DynamoDB TransactWriteItems with ConditionCheck.
Phase: Phase 0
"""

import botocore.exceptions
from spikes.helper import get_client

def run():
    ddb = get_client("dynamodb")
    table_name = "SpikeS5Table"

    print("[S5] Testing TransactWriteItems with ConditionCheck...")
    try:
        ddb.create_table(
            TableName=table_name,
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] != "ResourceInUseException":
            raise

    # Seed items
    ddb.put_item(TableName=table_name, Item={"pk": {"S": "itemA"}, "epoch": {"N": "1"}})
    ddb.put_item(TableName=table_name, Item={"pk": {"S": "itemB"}, "val": {"S": "val_initial"}})

    # Test 1: Condition passes
    pass_ok = False
    try:
        ddb.transact_write_items(
            TransactItems=[
                {
                    "ConditionCheck": {
                        "TableName": table_name,
                        "Key": {"pk": {"S": "itemA"}},
                        "ConditionExpression": "epoch = :expected_epoch",
                        "ExpressionAttributeValues": {":expected_epoch": {"N": "1"}},
                    }
                },
                {
                    "Update": {
                        "TableName": table_name,
                        "Key": {"pk": {"S": "itemB"}},
                        "UpdateExpression": "SET #v = :val",
                        "ExpressionAttributeNames": {"#v": "val"},
                        "ExpressionAttributeValues": {":val": {"S": "updated_by_tx"}},
                    }
                },
            ]
        )
        print("[S5] Valid transaction committed successfully.")
        pass_ok = True
    except Exception as e:
        print(f"[S5] Valid transaction failed: {e}")

    # Test 2: Condition fails
    fail_ok = False
    try:
        ddb.transact_write_items(
            TransactItems=[
                {
                    "ConditionCheck": {
                        "TableName": table_name,
                        "Key": {"pk": {"S": "itemA"}},
                        "ConditionExpression": "epoch = :expected_epoch",
                        "ExpressionAttributeValues": {":expected_epoch": {"N": "999"}},
                    }
                },
                {
                    "Update": {
                        "TableName": table_name,
                        "Key": {"pk": {"S": "itemB"}},
                        "UpdateExpression": "SET #v = :val",
                        "ExpressionAttributeNames": {"#v": "val"},
                        "ExpressionAttributeValues": {":val": {"S": "should_not_apply"}},
                    }
                },
            ]
        )
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "TransactionCanceledException":
            print("[S5] Condition failure raised TransactionCanceledException as expected.")
            fail_ok = True
        else:
            print(f"[S5] Unexpected error: {e}")

    # Cleanup
    try:
        ddb.delete_table(TableName=table_name)
    except Exception:
        pass

    if pass_ok and fail_ok:
        print("[S5] PASS: TransactWriteItems with ConditionCheck is fully supported.")
        return True
    else:
        print("[S5] FAIL: TransactWriteItems condition check not supported.")
        return False

if __name__ == "__main__":
    success = run()
    exit(0 if success else 1)
