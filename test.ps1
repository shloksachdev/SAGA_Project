<#
Tests all 4 saga Lambda functions (both forward and compensating actions)
without deploying or redeploying anything -- use this to verify the current
deployed state, e.g. after a restart, or before wiring them into Step
Functions / EventBridge.

Same "no silent errors" checking as deploy-lambda.ps1: checks the actual
exit code AND checks for FunctionError in the invoke response, since a
crashed Lambda still returns StatusCode 200.

Usage: .\test.ps1
Exit code 0 = all 8 tests passed. Exit code 1 = at least one failed.
#>

$Endpoint = "http://localhost:4566"
$Region = "us-east-1"

$env:AWS_ACCESS_KEY_ID = "test"
$env:AWS_SECRET_ACCESS_KEY = "test"
$env:AWS_DEFAULT_REGION = $Region

# The 4 services and their forward/compensate action names, matching
# what was used when each was deployed with deploy-lambda.ps1.
$Services = @(
    @{ Name = "Order";        Forward = "create";  Compensate = "cancel" }
    @{ Name = "Payment";      Forward = "charge";  Compensate = "compensate" }
    @{ Name = "Inventory";    Forward = "reserve"; Compensate = "release" }
    @{ Name = "Notification"; Forward = "notify";  Compensate = "unnotify" }
)

$OrderId = "order-123"

# --- Preflight ---

$awsCheck = Get-Command aws -ErrorAction SilentlyContinue
if (-not $awsCheck) {
    Write-Host "ERROR: 'aws' not found on PATH. Open a new PowerShell window and try again." -ForegroundColor Red
    exit 1
}

try {
    $health = Invoke-WebRequest -Uri "$Endpoint/_localstack/health" -UseBasicParsing -TimeoutSec 3
    if ($health.StatusCode -ne 200) {
        Write-Host "ERROR: LocalStack health check returned status $($health.StatusCode)." -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "ERROR: Could not reach LocalStack at $Endpoint -- is 'docker compose up -d' running?" -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# --- Test helper: same explicit checks as deploy-lambda.ps1's version ---

function Invoke-LambdaTest {
    param(
        [Parameter(Mandatory = $true)][string]$FunctionName,
        [Parameter(Mandatory = $true)][string]$Action,
        [Parameter(Mandatory = $true)][string]$OrderId
    )

    $payloadPath = Join-Path $env:TEMP "$FunctionName-$Action-payload.json"
    $responsePath = Join-Path $env:TEMP "$FunctionName-$Action-response.json"

    @{ action = $Action; orderId = $OrderId } | ConvertTo-Json -Compress | Set-Content -Path $payloadPath -Encoding ascii

    $invokeMeta = & aws --endpoint-url=$Endpoint --region $Region lambda invoke --function-name $FunctionName --payload "fileb://$payloadPath" $responsePath 2>&1
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        return @{ Passed = $false; Detail = "aws lambda invoke failed (exit $exitCode): $($invokeMeta | Out-String)" }
    }

    $metaJson = $null
    try { $metaJson = ($invokeMeta | Out-String) | ConvertFrom-Json } catch { }

    if ($metaJson -and $metaJson.PSObject.Properties.Name -contains "FunctionError") {
        $body = if (Test-Path $responsePath) { Get-Content $responsePath -Raw } else { "(no response file)" }
        return @{ Passed = $false; Detail = "FunctionError = $($metaJson.FunctionError). Body: $body" }
    }

    if (-not (Test-Path $responsePath)) {
        return @{ Passed = $false; Detail = "No response file was written." }
    }

    return @{ Passed = $true; Detail = (Get-Content $responsePath -Raw) }
}

# --- Run all tests ---

Write-Host "=== Testing all 4 Lambda functions ===" -ForegroundColor Cyan
Write-Host ""

$results = @()

foreach ($service in $Services) {
    Write-Host "-- $($service.Name) --"

    $forwardResult = Invoke-LambdaTest -FunctionName $service.Name -Action $service.Forward -OrderId $OrderId
    $status = if ($forwardResult.Passed) { "PASS" } else { "FAIL" }
    $color = if ($forwardResult.Passed) { "Green" } else { "Red" }
    Write-Host "  [$status] $($service.Forward): $($forwardResult.Detail)" -ForegroundColor $color
    $results += @{ Service = $service.Name; Action = $service.Forward; Passed = $forwardResult.Passed }

    $compensateResult = Invoke-LambdaTest -FunctionName $service.Name -Action $service.Compensate -OrderId $OrderId
    $status = if ($compensateResult.Passed) { "PASS" } else { "FAIL" }
    $color = if ($compensateResult.Passed) { "Green" } else { "Red" }
    Write-Host "  [$status] $($service.Compensate): $($compensateResult.Detail)" -ForegroundColor $color
    $results += @{ Service = $service.Name; Action = $service.Compensate; Passed = $compensateResult.Passed }

    Write-Host ""
}

# --- Summary ---

$passed = ($results | Where-Object { $_.Passed }).Count
$total = $results.Count

Write-Host "=== Summary: $passed / $total tests passed ===" -ForegroundColor Cyan

if ($passed -eq $total) {
    Write-Host "All Lambda functions are deployed and working." -ForegroundColor Green
    exit 0
} else {
    Write-Host "Some tests failed -- see red output above for which function/action and why." -ForegroundColor Red
    exit 1
}
