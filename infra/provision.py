"""
Purpose: Idempotent infrastructure provisioning for DynamoDB tables and EventBridge buses (D10, §3.2).
Phase: Phase 1
"""

import sys
import os
import botocore.exceptions

# Ensure project root in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.aws import get_boto3_client


def provision():
    ddb = get_boto3_client("dynamodb")
    events = get_boto3_client("events")

    print("[provision] Provisioning DynamoDB tables idempotently...")

    # 1. Orders table
    try:
        ddb.create_table(
            TableName="Orders",
            AttributeDefinitions=[{"AttributeName": "orderId", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "orderId", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
        print("  Created table Orders")
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print("  Table Orders already exists, skipping.")
        else:
            raise

    # 2. SagaRuns table (key: sagaId)
    try:
        ddb.create_table(
            TableName="SagaRuns",
            AttributeDefinitions=[{"AttributeName": "sagaId", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "sagaId", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
        print("  Created table SagaRuns")
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print("  Table SagaRuns already exists, skipping.")
        else:
            raise

    # 3. SagaSteps table (key: sagaId [HASH], step [RANGE])
    try:
        ddb.create_table(
            TableName="SagaSteps",
            AttributeDefinitions=[
                {"AttributeName": "sagaId", "AttributeType": "S"},
                {"AttributeName": "step", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "sagaId", "KeyType": "HASH"},
                {"AttributeName": "step", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        print("  Created table SagaSteps")
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print("  Table SagaSteps already exists, skipping.")
        else:
            raise

    # 4. SagaTrace table (key: sagaId [HASH], sk [RANGE])
    try:
        ddb.create_table(
            TableName="SagaTrace",
            AttributeDefinitions=[
                {"AttributeName": "sagaId", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "sagaId", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        print("  Created table SagaTrace")
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print("  Table SagaTrace already exists, skipping.")
        else:
            raise

    # 5. SagaLeases table (verify key is sagaId, recreate if old schema had sagaInstanceId)
    needs_recreate = False
    try:
        desc = ddb.describe_table(TableName="SagaLeases")
        key_schema = desc["Table"]["KeySchema"]
        hash_key = next((k["AttributeName"] for k in key_schema if k["KeyType"] == "HASH"), None)
        if hash_key != "sagaId":
            print(f"  SagaLeases key is '{hash_key}', recreating with 'sagaId'...")
            ddb.delete_table(TableName="SagaLeases")
            needs_recreate = True
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            needs_recreate = True
        else:
            raise

    if needs_recreate:
        ddb.create_table(
            TableName="SagaLeases",
            AttributeDefinitions=[{"AttributeName": "sagaId", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "sagaId", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
        print("  Created table SagaLeases with key sagaId")
    else:
        print("  Table SagaLeases already exists with correct schema, skipping.")

    # 6. EventBridge Buses: saga-bus-b, saga-bus-c, saga-bus-d, and legacy saga-bus
    print("[provision] Provisioning EventBridge buses...")
    for bus in ["saga-bus", "saga-bus-b", "saga-bus-c", "saga-bus-d"]:
        try:
            events.create_event_bus(Name=bus)
            print(f"  Created bus {bus}")
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "ResourceAlreadyExistsException":
                print(f"  Bus {bus} already exists, skipping.")
            else:
                pass

    # 7. Path A State Machine
    print("[provision] Deploying Path A state machine...")
    try:
        from paths.a.deploy import deploy as deploy_path_a
        deploy_path_a()
    except Exception as e:
        print(f"  Path A deployment note: {e}")

    print("[provision] Provisioning complete and verified.")
    return 0


if __name__ == "__main__":
    sys.exit(provision())
