"""
Purpose: Deploy generic Lambda step handlers Step1 ... Step6 for wide-fan workloads (Phase 7B).
Phase: Phase 7B
"""

import os
import sys
import time
import botocore.exceptions

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.aws import get_boto3_client
from infra.package import build_zip

ROLE_ARN = "arn:aws:iam::000000000000:role/SmokeTestRole"


def deploy_generic_steps():
    zip_path = os.path.join(PROJECT_ROOT, "Generic.zip")
    build_zip("generic_handler.py", "Generic.zip")

    with open(zip_path, "rb") as f:
        zip_bytes = f.read()

    lambda_client = get_boto3_client("lambda")

    for i in range(1, 7):
        func_name = f"Step{i}"
        env_vars = {"STEP_NAME": func_name}

        try:
            lambda_client.get_function(FunctionName=func_name)
            print(f"[deploy-generic] Updating code for {func_name}...")
            lambda_client.update_function_code(
                FunctionName=func_name,
                ZipFile=zip_bytes,
            )
            # Wait for update in progress
            for _ in range(30):
                desc = lambda_client.get_function_configuration(FunctionName=func_name)
                if desc.get("LastUpdateStatus") != "InProgress":
                    break
                time.sleep(0.5)

            lambda_client.update_function_configuration(
                FunctionName=func_name,
                Timeout=60,
                Environment={"Variables": env_vars},
            )
            print(f"[deploy-generic] {func_name} updated.")
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] in ("ResourceNotFoundException", "404"):
                print(f"[deploy-generic] Creating function {func_name}...")
                lambda_client.create_function(
                    FunctionName=func_name,
                    Runtime="python3.12",
                    Role=ROLE_ARN,
                    Handler="generic_handler.lambda_handler",
                    Code={"ZipFile": zip_bytes},
                    Timeout=60,
                    Environment={"Variables": env_vars},
                )
                print(f"[deploy-generic] {func_name} created.")
            else:
                raise

    print("[deploy-generic] All Step1 ... Step6 functions deployed successfully.")


if __name__ == "__main__":
    deploy_generic_steps()
