<#
Recreates the full Week 1 LocalStack baseline for the saga pattern project.
Run this after every LocalStack restart -- nothing survives on the Hobby tier
without the paid Persistence feature, so treat this script as the source of
truth instead of relying on anything sticking around.

Usage:   .\setup.ps1
Requires: AWS CLI v2 on PATH (run 'aws --version' to check), LocalStack
already running on localhost:4566 (docker compose up -d)
#>

$Endpoint  = "http://localhost:4566"
$Region    = "us-east-1"
$AccountId = "000000000000"

$env:AWS_ACCESS_KEY_ID     = "test"
$env:AWS_SECRET_ACCESS_KEY = "test"
$env:AWS_DEFAULT_REGION    = $Region

function Invoke-Aws {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string]$AlreadyExistsMarker = $null
    )

    $output = & aws --endpoint-url=$Endpoint --region $Region @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    $outputText = ($output | Out-String)

    if ($exitCode -eq 0) {
        Write-Host "  OK" -ForegroundColor Green
        return $output
    }

    if ($AlreadyExistsMarker -and $outputText -match $AlreadyExistsMarker) {
        Write-Host "  Already exists, skipping." -ForegroundColor Yellow
        return $output
    }

    Write-Host "  FAILED (exit code $exitCode):" -ForegroundColor Red
    Write-Host "  $outputText" -ForegroundColor Red
    return $null
}

Write-Host "=== Checking aws CLI is available ===" -ForegroundColor Cyan
$awsCheck = Get-Command aws -ErrorAction SilentlyContinue
if (-not $awsCheck) {
    Write-Host "'aws' was not found on PATH in this shell. Open a new PowerShell window (PATH changes need a fresh session) and try again." -ForegroundColor Red
    exit 1
}
Write-Host "  Found aws at $($awsCheck.Source)"

Write-Host ""
Write-Host "=== Waiting for LocalStack to be ready ===" -ForegroundColor Cyan
$ready = $false
for ($i = 1; $i -le 30; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "$Endpoint/_localstack/health" -UseBasicParsing -TimeoutSec 5
        if ($resp.StatusCode -eq 200) {
            Write-Host "LocalStack is up."
            $ready = $true
            break
        }
    } catch {
        # not up yet, keep waiting
    }
    Write-Host "  waiting... ($i/30)"
    Start-Sleep -Seconds 2
}
if (-not $ready) {
    Write-Host "LocalStack did not respond after 60 seconds. Is 'docker compose up -d' running?" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== DynamoDB tables ===" -ForegroundColor Cyan

Write-Host "Creating Orders table..."
Invoke-Aws -AlreadyExistsMarker "ResourceInUseException" -Arguments @(
    "dynamodb", "create-table",
    "--table-name", "Orders",
    "--attribute-definitions", "AttributeName=orderId,AttributeType=S",
    "--key-schema", "AttributeName=orderId,KeyType=HASH",
    "--billing-mode", "PAY_PER_REQUEST"
) | Out-Null

Write-Host "Creating SagaLeases table..."
Invoke-Aws -AlreadyExistsMarker "ResourceInUseException" -Arguments @(
    "dynamodb", "create-table",
    "--table-name", "SagaLeases",
    "--attribute-definitions", "AttributeName=sagaInstanceId,AttributeType=S",
    "--key-schema", "AttributeName=sagaInstanceId,KeyType=HASH",
    "--billing-mode", "PAY_PER_REQUEST"
) | Out-Null

Write-Host ""
Write-Host "=== CloudWatch log group ===" -ForegroundColor Cyan

Write-Host "Creating log group..."
Invoke-Aws -AlreadyExistsMarker "ResourceAlreadyExistsException" -Arguments @(
    "logs", "create-log-group",
    "--log-group-name", "/saga/smoke-test"
) | Out-Null

Write-Host ""
Write-Host "=== IAM role for Step Functions ===" -ForegroundColor Cyan

$trustPolicyPath = Join-Path $env:TEMP "trust-policy.json"
@'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "states.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
'@ | Set-Content -Path $trustPolicyPath -Encoding ascii

$trustPolicyUri = "file://" + ($trustPolicyPath -replace '\\', '/')

Write-Host "Creating SmokeTestRole..."
Invoke-Aws -AlreadyExistsMarker "EntityAlreadyExists" -Arguments @(
    "iam", "create-role",
    "--role-name", "SmokeTestRole",
    "--assume-role-policy-document", $trustPolicyUri
) | Out-Null

Remove-Item $trustPolicyPath -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=== EventBridge bus, rule, and target ===" -ForegroundColor Cyan

Write-Host "Creating saga-bus..."
Invoke-Aws -AlreadyExistsMarker "ResourceAlreadyExistsException" -Arguments @(
    "events", "create-event-bus",
    "--name", "saga-bus"
) | Out-Null

$patternPath = Join-Path $env:TEMP "pattern.json"
'{"source": ["saga.smoketest"]}' | Set-Content -Path $patternPath -Encoding ascii
$patternUri = "file://" + ($patternPath -replace '\\', '/')

Write-Host "Creating smoke-test-rule..."
Invoke-Aws -Arguments @(
    "events", "put-rule",
    "--name", "smoke-test-rule",
    "--event-bus-name", "saga-bus",
    "--event-pattern", $patternUri
) | Out-Null

Remove-Item $patternPath -ErrorAction SilentlyContinue

Write-Host "Attaching target to smoke-test-rule..."
Invoke-Aws -Arguments @(
    "events", "put-targets",
    "--rule", "smoke-test-rule",
    "--event-bus-name", "saga-bus",
    "--targets", "Id=1,Arn=arn:aws:logs:${Region}:${AccountId}:log-group:/saga/smoke-test:*"
) | Out-Null

Write-Host ""
Write-Host "=== Step Functions state machine ===" -ForegroundColor Cyan

$aslPath = Join-Path $env:TEMP "smoke-test.asl.json"
@'
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
'@ | Set-Content -Path $aslPath -Encoding ascii

$aslUri = "file://" + ($aslPath -replace '\\', '/')

Write-Host "Creating saga-smoke-test state machine..."
Invoke-Aws -AlreadyExistsMarker "StateMachineAlreadyExists" -Arguments @(
    "stepfunctions", "create-state-machine",
    "--name", "saga-smoke-test",
    "--definition", $aslUri,
    "--role-arn", "arn:aws:iam::${AccountId}:role/SmokeTestRole"
) | Out-Null

Remove-Item $aslPath -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=== Done. Current state: ===" -ForegroundColor Cyan

Write-Host ""
Write-Host "DynamoDB tables:"
& aws --endpoint-url=$Endpoint --region $Region dynamodb list-tables --output text

Write-Host ""
Write-Host "EventBridge buses:"
& aws --endpoint-url=$Endpoint --region $Region events list-event-buses --output text

Write-Host ""
Write-Host "IAM roles:"
& aws --endpoint-url=$Endpoint --region $Region iam list-roles --query "Roles[].RoleName" --output text

Write-Host ""
Write-Host "State machines:"
& aws --endpoint-url=$Endpoint --region $Region stepfunctions list-state-machines --query "stateMachines[].name" --output text

Write-Host ""
Write-Host "=== Verifying the chain actually works (not just that resources exist) ===" -ForegroundColor Cyan

$stateMachineArn = "arn:aws:states:${Region}:${AccountId}:stateMachine:saga-smoke-test"
Write-Host "Starting a test execution..."
$startResult = Invoke-Aws -Arguments @(
    "stepfunctions", "start-execution",
    "--state-machine-arn", $stateMachineArn,
    "--input", "{}"
)

if ($startResult) {
    $executionArn = ($startResult | Out-String | ConvertFrom-Json).executionArn
    Write-Host "  Execution started: $executionArn"
    Start-Sleep -Seconds 2

    $status = & aws --endpoint-url=$Endpoint --region $Region stepfunctions describe-execution --execution-arn $executionArn --query "status" --output text
    Write-Host "  Execution status: $status"

    Write-Host "  Checking the log group for the resulting event..."
    & aws --endpoint-url=$Endpoint --region $Region logs filter-log-events --log-group-name /saga/smoke-test --query "events[-1].message" --output text
} else {
    Write-Host "  Could not start execution -- check the state machine creation output above for errors." -ForegroundColor Red
}