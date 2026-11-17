"""
Purpose: Spike S7 - Verify EventBridge target RetryPolicy + DeadLetterConfig (SQS).
Phase: Phase 0
"""

import json
import time
import botocore.exceptions
from spikes.helper import ROLE_ARN, create_zip_bytes, get_client

def run():
    events = get_client("events")
    lambda_client = get_client("lambda")
    sqs = get_client("sqs")

    bus_name = "saga-bus"
    rule_name = "SpikeS7Rule"
    fn_name = "SpikeS7Fail"
    queue_name = "SpikeS7DLQ"

    print("[S7] Setting up SQS DLQ, failing Lambda, and EventBridge rule...")

    # 1. Create SQS DLQ
    q_resp = sqs.create_queue(QueueName=queue_name)
    q_url = q_resp["QueueUrl"]
    q_attrs = sqs.get_queue_attributes(QueueUrl=q_url, AttributeNames=["QueueArn"])
    q_arn = q_attrs["Attributes"]["QueueArn"]

    # 2. Deploy failing Lambda
    handler_code = """
def lambda_handler(event, context):
    print("[S7] Failing Lambda invoked, throwing error...")
    raise RuntimeError("Spike S7 forced failure")
"""
    zip_bytes = create_zip_bytes({"s7_fail.py": handler_code})
    try:
        lambda_client.get_function(FunctionName=fn_name)
        lambda_client.update_function_code(FunctionName=fn_name, ZipFile=zip_bytes)
    except botocore.exceptions.ClientError:
        lambda_client.create_function(
            FunctionName=fn_name,
            Runtime="python3.12",
            Role=ROLE_ARN,
            Handler="s7_fail.lambda_handler",
            Code={"ZipFile": zip_bytes},
            Timeout=5,
        )

    fn_arn = f"arn:aws:lambda:us-east-1:000000000000:function:{fn_name}"

    # 3. Create Rule
    events.put_rule(
        Name=rule_name,
        EventBusName=bus_name,
        EventPattern=json.dumps({"source": ["spike.s7"]}),
    )

    # 4. Lambda permission
    try:
        lambda_client.add_permission(
            FunctionName=fn_name,
            StatementId="SpikeS7InvokePerm",
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=f"arn:aws:events:us-east-1:000000000000:rule/{bus_name}/{rule_name}",
        )
    except botocore.exceptions.ClientError:
        pass

    # 5. Put target with RetryPolicy and DeadLetterConfig
    events.put_targets(
        Rule=rule_name,
        EventBusName=bus_name,
        Targets=[
            {
                "Id": "1",
                "Arn": fn_arn,
                "RetryPolicy": {
                    "MaximumRetryAttempts": 0,
                    "MaximumEventAgeInSeconds": 60,
                },
                "DeadLetterConfig": {
                    "Arn": q_arn,
                },
            }
        ],
    )

    time.sleep(1)

    # 6. Put event
    test_msg = {"spike": "s7", "token": "dlq-token-123"}
    events.put_events(
        Entries=[
            {
                "Source": "spike.s7",
                "DetailType": "FailTest",
                "Detail": json.dumps(test_msg),
                "EventBusName": bus_name,
            }
        ]
    )

    # 7. Poll SQS DLQ
    passed = False
    for _ in range(15):
        time.sleep(1)
        res = sqs.receive_message(
            QueueUrl=q_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=1,
        )
        messages = res.get("Messages", [])
        if messages:
            print(f"[S7] Message received in DLQ: {messages[0]['Body']}")
            passed = True
            break

    # Cleanup
    try:
        events.remove_targets(Rule=rule_name, EventBusName=bus_name, Ids=["1"])
        events.delete_rule(Name=rule_name, EventBusName=bus_name)
        lambda_client.delete_function(FunctionName=fn_name)
        sqs.delete_queue(QueueUrl=q_url)
    except Exception:
        pass

    if passed:
        print("[S7] PASS: EventBridge target RetryPolicy + DeadLetterConfig (SQS) works as expected.")
        return True
    else:
        print("[S7] FAIL: Event did not reach SQS DLQ (or target RetryPolicy/DLQ not supported).")
        return False

if __name__ == "__main__":
    success = run()
    exit(0 if success else 1)
