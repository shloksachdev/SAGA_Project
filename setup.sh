#!/usr/bin/env bash
# Purpose: Baseline environment setup mirroring setup.ps1 for Unix/WSL/Git Bash.
# Phase: Phase 0

set -euo pipefail

ENDPOINT="http://localhost:4566"
REGION="us-east-1"
ACCOUNT_ID="000000000000"

export AWS_ACCESS_KEY_ID="test"
export AWS_SECRET_ACCESS_KEY="test"
export AWS_DEFAULT_REGION="$REGION"

invoke_aws() {
    local marker="${1:-}"
    shift || true
    set +e
    output=$(aws --endpoint-url="$ENDPOINT" --region "$REGION" "$@" 2>&1)
    exit_code=$?
    set -e

    if [ $exit_code -eq 0 ]; then
        echo "  OK"
        return 0
    fi

    if [ -n "$marker" ] && echo "$output" | grep -q "$marker"; then
        echo "  Already exists, skipping."
        return 0
    fi

    echo "  FAILED (exit code $exit_code):"
    echo "  $output"
    return $exit_code
}

echo "=== Checking aws CLI is available ==="
if ! command -v aws >/dev/null 2>&1; then
    echo "'aws' was not found on PATH. Install AWS CLI v2 and try again."
    exit 1
fi
echo "  Found aws: $(command -v aws)"

echo ""
echo "=== Waiting for LocalStack to be ready ==="
ready=false
for i in $(seq 1 30); do
    if curl -s -f "$ENDPOINT/_localstack/health" >/dev/null 2>&1; then
        echo "LocalStack is up."
        ready=true
        break
    fi
    echo "  waiting... ($i/30)"
    sleep 2
done

if [ "$ready" != "true" ]; then
    echo "LocalStack did not respond after 60 seconds. Is 'docker compose up -d' running?"
    exit 1
fi

echo ""
echo "=== DynamoDB tables ==="
echo "Creating Orders table..."
invoke_aws "ResourceInUseException" dynamodb create-table \
    --table-name Orders \
    --attribute-definitions AttributeName=orderId,AttributeType=S \
    --key-schema AttributeName=orderId,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST || true

echo "Creating SagaLeases table..."
invoke_aws "ResourceInUseException" dynamodb create-table \
    --table-name SagaLeases \
    --attribute-definitions AttributeName=sagaInstanceId,AttributeType=S \
    --key-schema AttributeName=sagaInstanceId,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST || true

echo ""
echo "=== CloudWatch log group ==="
echo "Creating log group..."
invoke_aws "ResourceAlreadyExistsException" logs create-log-group \
    --log-group-name /saga/smoke-test || true

echo ""
echo "=== IAM role for Step Functions ==="
echo "Creating SmokeTestRole..."
invoke_aws "EntityAlreadyExists" iam create-role \
    --role-name SmokeTestRole \
    --assume-role-policy-document file://trust-policy.json || true

echo ""
echo "=== EventBridge bus, rule, and target ==="
echo "Creating saga-bus..."
invoke_aws "ResourceAlreadyExistsException" events create-event-bus \
    --name saga-bus || true

PATTERN_TMP=$(mktemp)
echo '{"source": ["saga.smoketest"]}' > "$PATTERN_TMP"
echo "Creating smoke-test-rule..."
invoke_aws "" events put-rule \
    --name smoke-test-rule \
    --event-bus-name saga-bus \
    --event-pattern "file://$PATTERN_TMP" || true
rm -f "$PATTERN_TMP"

echo "Attaching target to smoke-test-rule..."
invoke_aws "" events put-targets \
    --rule smoke-test-rule \
    --event-bus-name saga-bus \
    --targets "Id=1,Arn=arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:/saga/smoke-test:*" || true

echo ""
echo "=== Step Functions state machine ==="
ASL_TMP=$(mktemp)
cat << 'EOF' > "$ASL_TMP"
{
  "Comment": "SFN -> EventBridge smoke test",
  "StartAt": "PublishToEventBridge",
  "States": {
    "PublishToEventBridge": {
      "Type": "Task",
      "Resource": "arn:aws:states:::events:putEvents",
      "Parameters": {
        "Entries": [
          {
            "Source": "saga.smoketest",
            "DetailType": "CompensationNeeded",
            "EventBusName": "saga-bus",
            "Detail": "{\"sagaInstanceId\": \"smoke-test-001\"}"
          }
        ]
      },
      "End": true
    }
  }
}
EOF

echo "Creating saga-smoke-test state machine..."
invoke_aws "StateMachineAlreadyExists" stepfunctions create-state-machine \
    --name saga-smoke-test \
    --definition "file://$ASL_TMP" \
    --role-arn "arn:aws:iam:${ACCOUNT_ID}:role/SmokeTestRole" || true
rm -f "$ASL_TMP"

echo ""
echo "=== Done. Current state: ==="
echo "DynamoDB tables:"
aws --endpoint-url="$ENDPOINT" --region "$REGION" dynamodb list-tables --output text

echo "EventBridge buses:"
aws --endpoint-url="$ENDPOINT" --region "$REGION" events list-event-buses --output text

echo "IAM roles:"
aws --endpoint-url="$ENDPOINT" --region "$REGION" iam list-roles --query "Roles[].RoleName" --output text

echo "State machines:"
aws --endpoint-url="$ENDPOINT" --region "$REGION" stepfunctions list-state-machines --query "stateMachines[].name" --output text

echo ""
echo "=== Verifying the chain actually works ==="
STATE_MACHINE_ARN="arn:aws:states:${REGION}:${ACCOUNT_ID}:stateMachine:saga-smoke-test"
echo "Starting test execution..."
START_OUTPUT=$(aws --endpoint-url="$ENDPOINT" --region "$REGION" stepfunctions start-execution --state-machine-arn "$STATE_MACHINE_ARN" --input "{}" --output json 2>/dev/null || echo "")

if [ -n "$START_OUTPUT" ]; then
    EXEC_ARN=$(echo "$START_OUTPUT" | grep -o '"executionArn": "[^"]*' | cut -d'"' -f4)
    echo "  Execution started: $EXEC_ARN"
    sleep 2
    STATUS=$(aws --endpoint-url="$ENDPOINT" --region "$REGION" stepfunctions describe-execution --execution-arn "$EXEC_ARN" --query "status" --output text)
    echo "  Execution status: $STATUS"
    echo "  Checking log group for event..."
    aws --endpoint-url="$ENDPOINT" --region "$REGION" logs filter-log-events --log-group-name /saga/smoke-test --query "events[-1].message" --output text || true
fi

echo ""
echo "=== Running infra/provision.py for shared saga tables and buses ==="
python infra/provision.py
