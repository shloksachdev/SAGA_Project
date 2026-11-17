"""
Purpose: Spike S1 - Verify EventBridge rule -> Lambda delivers $.detail as Lambda event.
Phase: Phase 0
"""

import json
import time
import botocore.exceptions
from spikes.helper import ROLE_ARN, create_zip_bytes, get_client, get_resource

def run():
    events = get_client("events")
    lambda_client = get_client("lambda")
    ddb = get_resource("dynamodb")
    ddb_client = get_client("dynamodb")

    table_name = "SpikeS1Table"
    fn_name = "SpikeS1Recorder"
    rule_name = "SpikeS1Rule"
    bus_name = "saga-bus"

    print("[S1] Setting up resources...")
    # 1. Create table
    try:
        ddb_client.create_table(
            TableName=table_name,
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
    except botocore.exceptions.ClientError as e:
        if e.response["Error"]["Code"] != "ResourceInUseException":
            raise
    table = ddb.Table(table_name)

    # 2. Deploy Lambda
    handler_code = """
import os, boto3
dynamodb = boto3.resource("dynamodb", endpoint_url=os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566"), region_name="us-east-1")
table = dynamodb.Table("SpikeS1Table")
def lambda_handler(event, context):
    table.put_item(Item={"id": "s1_delivery", "event": event})
    return {"ok": True}
"""
    zip_bytes = create_zip_bytes({"spike_s1_handler.py": handler_code})
    try:
        lambda_client.get_function(FunctionName=fn_name)
        lambda_client.update_function_code(FunctionName=fn_name, ZipFile=zip_bytes)
    except botocore.exceptions.ClientError:
        lambda_client.create_function(
            FunctionName=fn_name,
            Runtime="python3.12",
            Role=ROLE_ARN,
            Handler="spike_s1_handler.lambda_handler",
            Code={"ZipFile": zip_bytes},
            Timeout=10,
        )

    # 3. Ensure bus exists
    try:
        events.create_event_bus(Name=bus_name)
    except botocore.exceptions.ClientError:
        pass

    # 4. Put rule
    events.put_rule(
        Name=rule_name,
        EventBusName=bus_name,
        EventPattern=json.dumps({"source": ["spike.s1"]}),
    )

    # 5. Add permission to Lambda
    try:
        lambda_client.add_permission(
            FunctionName=fn_name,
            StatementId="SpikeS1InvokePerm",
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=f"arn:aws:events:us-east-1:000000000000:rule/{bus_name}/{rule_name}",
        )
    except botocore.exceptions.ClientError:
        pass

    # 6. Put target with InputPath: $.detail
    fn_arn = f"arn:aws:lambda:us-east-1:000000000000:function:{fn_name}"
    events.put_targets(
        Rule=rule_name,
        EventBusName=bus_name,
        Targets=[{"Id": "1", "Arn": fn_arn, "InputPath": "$.detail"}],
    )

    time.sleep(1)

    # 7. Put event
    test_payload = {"customMessage": "hello_s1", "orderId": "s1-100"}
    events.put_events(
        Entries=[
            {
                "Source": "spike.s1",
                "DetailType": "Spike1Test",
                "Detail": json.dumps(test_payload),
                "EventBusName": bus_name,
            }
        ]
    )

    # 8. Poll table
    passed = False
    for _ in range(15):
        time.sleep(1)
        resp = table.get_item(Key={"id": "s1_delivery"})
        if "Item" in resp:
            received_event = resp["Item"].get("event", {})
            print(f"[S1] Received event in Lambda: {received_event}")
            if received_event == test_payload or (isinstance(received_event, dict) and received_event.get("customMessage") == "hello_s1" and "detail-type" not in received_event):
                passed = True
                break

    # Cleanup
    try:
        events.remove_targets(Rule=rule_name, EventBusName=bus_name, Ids=["1"])
        events.delete_rule(Name=rule_name, EventBusName=bus_name)
        lambda_client.delete_function(FunctionName=fn_name)
        table.delete()
    except Exception:
        pass

    if passed:
        print("[S1] PASS: EventBridge delivered $.detail directly to Lambda event.")
        return True
    else:
        print("[S1] FAIL: EventBridge did not deliver $.detail as expected.")
        return False

if __name__ == "__main__":
    success = run()
    exit(0 if success else 1)
