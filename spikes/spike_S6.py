"""
Purpose: Spike S6 - Verify Lambda invoking another Lambda synchronously from inside container (4 concurrent invokes).
Phase: Phase 0
"""

import json
import time
import botocore.exceptions
from spikes.helper import ROLE_ARN, create_zip_bytes, get_client

def wait_for_active(lambda_client, fn_name, timeout=15):
    for _ in range(timeout):
        try:
            cfg = lambda_client.get_function_configuration(FunctionName=fn_name)
            state = cfg.get("State", "Active")
            if state == "Active":
                return True
        except Exception:
            pass
        time.sleep(1)
    return True

def run():
    lambda_client = get_client("lambda")

    worker_name = "SpikeS6Worker"
    caller_name = "SpikeS6Caller"

    print("[S6] Deploying worker and caller Lambdas...")

    worker_code = """
import time
def lambda_handler(event, context):
    time.sleep(0.05)
    return {"worker_status": "OK", "worker_id": event.get("worker_id")}
"""
    worker_zip = create_zip_bytes({"worker.py": worker_code})
    try:
        lambda_client.get_function(FunctionName=worker_name)
        lambda_client.update_function_code(FunctionName=worker_name, ZipFile=worker_zip)
    except botocore.exceptions.ClientError:
        lambda_client.create_function(
            FunctionName=worker_name,
            Runtime="python3.12",
            Role=ROLE_ARN,
            Handler="worker.lambda_handler",
            Code={"ZipFile": worker_zip},
            Timeout=15,
        )

    caller_code = """
import json, os, boto3
from concurrent.futures import ThreadPoolExecutor

lambda_client = boto3.client(
    "lambda",
    endpoint_url=os.environ.get("AWS_ENDPOINT_URL", "http://localhost:4566"),
    region_name="us-east-1",
)

def call_one(wid):
    resp = lambda_client.invoke(
        FunctionName="SpikeS6Worker",
        InvocationType="RequestResponse",
        Payload=json.dumps({"worker_id": wid}),
    )
    return json.loads(resp["Payload"].read())

def lambda_handler(event, context):
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(call_one, range(4)))
    return {"results": results}
"""
    caller_zip = create_zip_bytes({"caller.py": caller_code})
    try:
        lambda_client.get_function(FunctionName=caller_name)
        lambda_client.update_function_code(FunctionName=caller_name, ZipFile=caller_zip)
    except botocore.exceptions.ClientError:
        lambda_client.create_function(
            FunctionName=caller_name,
            Runtime="python3.12",
            Role=ROLE_ARN,
            Handler="caller.lambda_handler",
            Code={"ZipFile": caller_zip},
            Timeout=30,
        )

    wait_for_active(lambda_client, worker_name)
    wait_for_active(lambda_client, caller_name)

    print("[S6] Invoking caller Lambda...")
    resp = lambda_client.invoke(
        FunctionName=caller_name,
        InvocationType="RequestResponse",
        Payload=b"{}",
    )

    passed = False
    if "FunctionError" not in resp:
        res_data = json.loads(resp["Payload"].read())
        results = res_data.get("results", [])
        print(f"[S6] Received results: {results}")
        if len(results) == 4 and all(r.get("worker_status") == "OK" for r in results):
            passed = True
    else:
        err = resp["Payload"].read().decode()
        print(f"[S6] FunctionError: {err}")

    # Cleanup
    try:
        lambda_client.delete_function(FunctionName=caller_name)
        lambda_client.delete_function(FunctionName=worker_name)
    except Exception:
        pass

    if passed:
        print("[S6] PASS: Lambda successfully invoked 4 concurrent Lambdas from inside container.")
        return True
    else:
        print("[S6] FAIL: Concurrent invocation from inside container failed.")
        return False

if __name__ == "__main__":
    success = run()
    exit(0 if success else 1)
