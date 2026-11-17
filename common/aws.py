"""
Purpose: AWS/LocalStack SDK client and resource factory.
Phase: Phase 1
"""

import os
from typing import Optional
import boto3

DEFAULT_ENDPOINT = "http://localhost:4566"
DEFAULT_REGION = "us-east-1"


def get_endpoint_url() -> Optional[str]:
    # LocalStack sets AWS_ENDPOINT_URL inside Lambda execution environments.
    # On the host or in tests, LOCALSTACK_ENDPOINT or DEFAULT_ENDPOINT is used.
    return (
        os.environ.get("AWS_ENDPOINT_URL")
        or os.environ.get("LOCALSTACK_ENDPOINT")
        or DEFAULT_ENDPOINT
    )


def get_region() -> str:
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or DEFAULT_REGION


def get_boto3_client(service_name: str, endpoint_url: Optional[str] = None):
    endpoint = endpoint_url or get_endpoint_url()
    return boto3.client(
        service_name,
        endpoint_url=endpoint,
        region_name=get_region(),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    )


def get_boto3_resource(service_name: str, endpoint_url: Optional[str] = None):
    endpoint = endpoint_url or get_endpoint_url()
    return boto3.resource(
        service_name,
        endpoint_url=endpoint,
        region_name=get_region(),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "test"),
    )


def get_table(table_name: str, endpoint_url: Optional[str] = None):
    dynamodb = get_boto3_resource("dynamodb", endpoint_url=endpoint_url)
    return dynamodb.Table(table_name)
