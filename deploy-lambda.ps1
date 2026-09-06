<#
Deploys a single Lambda function (zip + create-or-update) and tests both its
forward and compensating actions. Every step checks its actual result --
nothing here assumes success just because a command returned without
throwing, since 'aws lambda invoke' famously returns exit code 0 even when
the function itself errored (FunctionError in the response body).

Reusable for all 4 services -- just point it at a different handler file
and action names.

Usage:
  .\deploy-lambda.ps1 -FunctionName Payment    -HandlerFile payment_handler.py    -ForwardAction charge  -CompensateAction compensate
  .\deploy-lambda.ps1 -FunctionName Order      -HandlerFile order_handler.py      -ForwardAction create  -CompensateAction cancel
  .\deploy-lambda.ps1 -FunctionName Inventory  -HandlerFile inventory_handler.py  -ForwardAction reserve -CompensateAction release
  .\deploy-lambda.ps1 -FunctionName Notification -HandlerFile notification_handler.py -ForwardAction notify -CompensateAction unnotify

Exit code 0 = function deployed AND both test invocations genuinely
succeeded. Exit code 1 = something failed -- check the red output above
for exactly what and where.
#>

param(
    [Parameter(Mandatory = $true)][string]$FunctionName,
    [Parameter(Mandatory = $true)][string]$HandlerFile,
    [string]$ForwardAction = "charge",
    [string]$CompensateAction = "compensate",
    [string]$OrderId = "order-123",
    [string]$Role = "arn:aws:iam::000000000000:role/SmokeTestRole",
    [string]$Runtime = "python3.12"
)

$Endpoint = "http://localhost:4566"
$Region = "us-east-1"

$env:AWS_ACCESS_KEY_ID = "test"
$env:AWS_SECRET_ACCESS_KEY = "test"
$env:AWS_DEFAULT_REGION = $Region

$overallSuccess = $true

# --- Preflight checks: fail loudly and immediately, don't limp forward ---

$awsCheck = Get-Command aws -ErrorAction SilentlyContinue
if (-not $awsCheck) {
    Write-Host "ERROR: 'aws' not found on PATH. Open a new PowerShell window and try again." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $HandlerFile)) {
    Write-Host "ERROR: Handler file '$HandlerFile' not found in current directory ($(Get-Location))." -ForegroundColor Red
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

$handlerBaseName = [System.IO.Path]::GetFileNameWithoutExtension($HandlerFile)
$handlerEntryPoint = "$handlerBaseName.lambda_handler"
$zipPath = "$FunctionName.zip"

Write-Host "=== Deploying $FunctionName ===" -ForegroundColor Cyan

# --- Zip ---

if (Test-Path $zipPath) {
    Remove-Item $zipPath -ErrorAction Stop
}
Write-Host "Zipping $HandlerFile -> $zipPath ..."
Compress-Archive -Path $HandlerFile -DestinationPath $zipPath -Force

if (-not (Test-Path $zipPath)) {
    Write-Host "ERROR: Zip creation failed -- $zipPath does not exist after Compress-Archive." -ForegroundColor Red
    exit 1
}
Write-Host "  OK: $zipPath created."

# --- Create or update ---

$existing = & aws --endpoint-url=$Endpoint --region $Region lambda get-function --function-name $FunctionName 2>&1
$existsExitCode = $LASTEXITCODE

if ($existsExitCode -eq 0) {
    Write-Host "Function already exists -- updating code..."
    $updateOutput = & aws --endpoint-url=$Endpoint --region $Region lambda update-function-code --function-name $FunctionName --zip-file "fileb://$zipPath" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: update-function-code failed (exit $LASTEXITCODE):" -ForegroundColor Red
        Write-Host "  $($updateOutput | Out-String)" -ForegroundColor Red
        exit 1
    }
    Write-Host "  OK: code updated." -ForegroundColor Green
} else {
    Write-Host "Function doesn't exist yet -- creating..."
    $createOutput = & aws --endpoint-url=$Endpoint --region $Region lambda create-function --function-name $FunctionName --runtime $Runtime --handler $handlerEntryPoint --zip-file "fileb://$zipPath" --role $Role 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: create-function failed (exit $LASTEXITCODE):" -ForegroundColor Red
        Write-Host "  $($createOutput | Out-String)" -ForegroundColor Red
        exit 1
    }
    Write-Host "  OK: function created." -ForegroundColor Green
}

Start-Sleep -Seconds 1  # give LocalStack a moment to finish registering before invoking

# --- Test helper: checks exit code AND FunctionError, doesn't trust a clean exit code alone ---

function Invoke-LambdaTest {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$Action,
        [Parameter(Mandatory = $true)][string]$OrderId
    )

    Write-Host "Testing: $Label (action=$Action)"

    $payloadPath = Join-Path $env:TEMP "$FunctionName-$Action-payload.json"
    $responsePath = Join-Path $env:TEMP "$FunctionName-$Action-response.json"

    @{ action = $Action; orderId = $OrderId } | ConvertTo-Json -Compress | Set-Content -Path $payloadPath -Encoding ascii

    $invokeMeta = & aws --endpoint-url=$Endpoint --region $Region lambda invoke --function-name $FunctionName --payload "fileb://$payloadPath" $responsePath 2>&1
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        Write-Host "  FAILED: 'aws lambda invoke' itself failed (exit $exitCode):" -ForegroundColor Red
        Write-Host "  $($invokeMeta | Out-String)" -ForegroundColor Red
        return $false
    }

    $metaText = ($invokeMeta | Out-String)
    $metaJson = $null
    try { $metaJson = $metaText | ConvertFrom-Json } catch { }

    if ($metaJson -and $metaJson.PSObject.Properties.Name -contains "FunctionError") {
        Write-Host "  FAILED: Lambda reported FunctionError = $($metaJson.FunctionError)" -ForegroundColor Red
        Write-Host "  Response body:" -ForegroundColor Red
        Write-Host "  $(Get-Content $responsePath -Raw)" -ForegroundColor Red
        return $false
    }

    if (-not (Test-Path $responsePath)) {
        Write-Host "  FAILED: no response file was written to $responsePath." -ForegroundColor Red
        return $false
    }

    $responseBody = Get-Content $responsePath -Raw
    Write-Host "  OK: $responseBody" -ForegroundColor Green
    return $true
}

Write-Host ""
Write-Host "=== Testing $FunctionName ===" -ForegroundColor Cyan

$forwardOk = Invoke-LambdaTest -Label "forward action" -Action $ForwardAction -OrderId $OrderId
$compensateOk = Invoke-LambdaTest -Label "compensating action" -Action $CompensateAction -OrderId $OrderId

if (-not ($forwardOk -and $compensateOk)) {
    $overallSuccess = $false
}

Write-Host ""
if ($overallSuccess) {
    Write-Host "=== $FunctionName : DEPLOYED AND BOTH TESTS PASSED ===" -ForegroundColor Green
    exit 0
} else {
    Write-Host "=== $FunctionName : ONE OR MORE STEPS FAILED -- see red output above ===" -ForegroundColor Red
    exit 1
}
