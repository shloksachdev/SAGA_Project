<#
Full pipeline: deploys (or updates) all 4 saga Lambda functions in the
proper order (Order -> Payment -> Inventory -> Notification), via
deploy-lambda.ps1, then independently re-verifies all 4 with direct
invoke tests.

Same "no silent errors" checking throughout: checks the actual exit code
of every command AND checks for FunctionError in invoke responses, since
a crashed Lambda still returns StatusCode 200.

Usage: .\test.ps1
Requires deploy-lambda.ps1 in the same directory.
Exit code 0 = every deploy succeeded AND all 8 re-verification tests
passed. Exit code 1 = at least one deploy or test failed.
#>

$Endpoint = "http://localhost:4566"
$Region = "us-east-1"

$env:AWS_ACCESS_KEY_ID = "test"
$env:AWS_SECRET_ACCESS_KEY = "test"
$env:AWS_DEFAULT_REGION = $Region

# The 4 services, their handler files, and forward/compensate action
# names, in the proper deploy order: Order first (creates the DynamoDB
# item), then Payment, Inventory, Notification (each updates that same
# item). Deployment order doesn't strictly matter functionally, but
# matching the natural saga sequence makes the output easier to read.
$Services = @(
    @{ Name = "Order";        HandlerFile = "order_handler.py";        Forward = "create";  Compensate = "cancel" }
    @{ Name = "Payment";      HandlerFile = "payment_handler.py";      Forward = "charge";  Compensate = "compensate" }
    @{ Name = "Inventory";    HandlerFile = "inventory_handler.py";    Forward = "reserve"; Compensate = "release" }
    @{ Name = "Notification"; HandlerFile = "notification_handler.py"; Forward = "notify";  Compensate = "unnotify" }
)

$OrderId = "order-123"
$overallSuccess = $true

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

if (-not (Test-Path ".\deploy-lambda.ps1")) {
    Write-Host "ERROR: deploy-lambda.ps1 not found in current directory ($(Get-Location))." -ForegroundColor Red
    exit 1
}

# --- Deploy phase ---
#
# deploy-lambda.ps1 ends with 'exit 0' / 'exit 1'. Calling it directly as
# '& .\deploy-lambda.ps1 ...' would run it in THIS process, so its exit
# would terminate test.ps1 itself on the first failure, breaking the loop
# over the remaining services. Invoking it via 'powershell -File' instead
# runs it as a genuine child process -- its exit only ends that child, and
# $LASTEXITCODE afterward tells us how it went without taking test.ps1 down
# with it.

Write-Host "=== Deploying all 4 Lambda functions ===" -ForegroundColor Cyan
Write-Host ""

foreach ($service in $Services) {
    Write-Host "-- Deploying $($service.Name) --"

    powershell -NoProfile -File ".\deploy-lambda.ps1" `
        -FunctionName $service.Name `
        -HandlerFile $service.HandlerFile `
        -ForwardAction $service.Forward `
        -CompensateAction $service.Compensate

    $deployExitCode = $LASTEXITCODE

    if ($deployExitCode -eq 0) {
        Write-Host "  [DEPLOY OK] $($service.Name)" -ForegroundColor Green
    } else {
        Write-Host "  [DEPLOY FAILED] $($service.Name) (exit $deployExitCode) -- see output above for details" -ForegroundColor Red
        $overallSuccess = $false
    }

    Write-Host ""
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

# --- Test phase (independent re-verification, separate from deploy-lambda.ps1's own checks) ---

Write-Host "=== Re-verifying all 4 Lambda functions directly ===" -ForegroundColor Cyan
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

if ($passed -lt $total) {
    $overallSuccess = $false
}

Write-Host "=== Summary ===" -ForegroundColor Cyan
Write-Host "Re-verification: $passed / $total direct invoke tests passed"

if ($overallSuccess) {
    Write-Host "All 4 Lambdas deployed successfully and all tests passed." -ForegroundColor Green
    exit 0
} else {
    Write-Host "At least one deploy step or test failed -- see red output above for exactly which and why." -ForegroundColor Red
    exit 1
}
