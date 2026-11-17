"""
Purpose: Helper utility for spike scripts (boto3 clients and common zip creation).
Phase: Phase 0
"""

import io
import os
import zipfile
import boto3

ENDPOINT_URL = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
REGION = "us-east-1"
ROLE_ARN = "arn:aws:iam::000000000000:role/SmokeTestRole"

def get_client(service_name: str):
    return boto3.client(
        service_name,
        endpoint_url=ENDPOINT_URL,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )

def get_resource(service_name: str):
    return boto3.resource(
        service_name,
        endpoint_url=ENDPOINT_URL,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )

def create_zip_bytes(files_dict: dict) -> bytes:
    """Takes a dict of {filename: content_str} and returns zip bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, content in files_dict.items():
            zf.writestr(fname, content)
    buf.seek(0)
    return buf.read()
