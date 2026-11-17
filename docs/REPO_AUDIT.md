<!--
Purpose: Repository audit covering existing AWS/LocalStack resources, handlers, packaging, and divergences from SPEC.md.
Phase: Phase 0
-->

# Repository Audit (Phase 0)

## 1. Existing Resources & Infrastructure

### 1.1 DynamoDB Tables
Configured in `setup.ps1`:
- **`Orders`**:
  - Primary Key: `orderId` (String, HASH)
  - Billing Mode: `PAY_PER_REQUEST`
  - Used by all 4 existing handlers to record status updates and timestamps.
- **`SagaLeases`**:
  - Primary Key: `sagaInstanceId` (String, HASH)
  - Billing Mode: `PAY_PER_REQUEST`
  - *Divergence alert:* See Section 6 regarding `sagaInstanceId` vs `sagaId`.

### 1.2 EventBridge Resources
Configured in `setup.ps1`:
- **Bus**: `saga-bus`
- **Rule**: `smoke-test-rule`
  - Event pattern: `{"source": ["saga.smoketest"]}`
- **Target**: CloudWatch log group `/saga/smoke-test` (Target Id: 1)

### 1.3 IAM Role
Configured in `setup.ps1` / `trust-policy.json`:
- **Role Name**: `SmokeTestRole`
- **ARN**: `arn:aws:iam::000000000000:role/SmokeTestRole`
- **AssumeRole Policy**: `states.amazonaws.com` (AWS Step Functions)

### 1.4 Step Functions State Machine
Configured in `setup.ps1`:
- **Name**: `saga-smoke-test`
- **ARN**: `arn:aws:states:us-east-1:000000000000:stateMachine:saga-smoke-test`
- **Definition**: Single Task state `PublishToEventBridge` calling `arn:aws:states:::events:putEvents`, publishing `Source: saga.smoketest`, `DetailType: CompensationNeeded`, `Detail: {"sagaInstanceId": "smoke-test-001"}` to `saga-bus`.

### 1.5 CloudWatch Logs
Configured in `setup.ps1`:
- **Log Group**: `/saga/smoke-test`

---

## 2. Handler Shapes & Contracts

All four handlers share the same structural pattern:
- Entry point: `lambda_handler(event, context)`
- Dynamically selects forward vs. compensating logic via `event.get("action", default_action)`.
- Reaches DynamoDB table `Orders` via `boto3.resource("dynamodb", endpoint_url=os.environ.get("AWS_ENDPOINT_URL"), region_name=os.environ.get("AWS_REGION", "us-east-1"))`.
- Supports error simulation via `event.get("simulateFailure")`.

| Handler | Forward Action | Compensating Action | Input Shape | Forward Output | Compensate Output | Error Raised on Failure |
|---|---|---|---|---|---|---|
| `order_handler.py` | `create` | `cancel` | `{"action": "create"\|"cancel", "orderId": str, "simulateFailure": bool}` | `{"orderId": order_id, "status": "ORDER_CREATED"}` | `{"orderId": order_id, "status": "ORDER_CANCELLED"}` | `Exception("Simulated order creation failure")` |
| `payment_handler.py` | `charge` | `compensate` | `{"action": "charge"\|"compensate", "orderId": str, "simulateFailure": bool}` | `{"orderId": order_id, "status": "PAYMENT_COMPLETED"}` | `{"orderId": order_id, "status": "PAYMENT_COMPENSATED"}` | `Exception("Simulated payment failure")` |
| `inventory_handler.py` | `reserve` | `release` | `{"action": "reserve"\|"release", "orderId": str, "simulateFailure": bool}` | `{"orderId": order_id, "status": "INVENTORY_RESERVED"}` | `{"orderId": order_id, "status": "INVENTORY_RELEASED"}` | `Exception("Simulated inventory shortage")` |
| `notification_handler.py` | `notify` | `unnotify` | `{"action": "notify"\|"unnotify", "orderId": str, "simulateFailure": bool}` | `{"orderId": order_id, "status": "NOTIFICATION_SENT"}` | `{"orderId": order_id, "status": "NOTIFICATION_RETRACTED"}` | `Exception("Simulated notification delivery failure")` |

---

## 3. DynamoDB Access Pattern

Inside handlers:
```python
dynamodb = boto3.resource(
    "dynamodb",
    endpoint_url=os.environ.get("AWS_ENDPOINT_URL"),
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
)
table = dynamodb.Table(TABLE_NAME)
```
- In LocalStack Lambda container execution, LocalStack automatically injects `AWS_ENDPOINT_URL`.
- In test runners and client scripts on the host, `AWS_ENDPOINT_URL` is typically `http://localhost:4566`.
- Region defaults to `us-east-1`.
- Authentication uses dummy credentials `AWS_ACCESS_KEY_ID="test"`, `AWS_SECRET_ACCESS_KEY="test"`.

---

## 4. Lambda Packaging & Deployment

From `deploy-lambda.ps1`:
- **Zipping**: `Compress-Archive -Path $HandlerFile -DestinationPath $FunctionName.zip -Force`
- **Archive contents**: A single `.py` file per zip (e.g., `Order.zip` contains `order_handler.py`).
- **Handler entrypoint**: `<handler_base_name>.lambda_handler` (e.g. `order_handler.lambda_handler`).
- **Role**: `arn:aws:iam::000000000000:role/SmokeTestRole`
- **Runtime**: `python3.12`
- **Timeout & Memory**: Defaults (3 seconds timeout, 128 MB memory).

---

## 5. Region, Endpoints, and Credentials

- **Default Endpoint**: `http://localhost:4566`
- **Region**: `us-east-1`
- **Account ID**: `000000000000`
- **Credentials**:
  - `AWS_ACCESS_KEY_ID = "test"`
  - `AWS_SECRET_ACCESS_KEY = "test"`
  - `AWS_DEFAULT_REGION = "us-east-1"`

---

## 6. Divergences from SPEC.md

1. **`SagaLeases` Table Primary Key**:
   - `setup.ps1` sets the partition key to `sagaInstanceId` (`AttributeName=sagaInstanceId,KeyType=HASH`).
   - `SPEC.md` section 3.2 specifies partition key `sagaId` (S).
   - *Resolution for Phase 1*: Provisioning script should standardize on `sagaId` (or support both / recreate table as specified in SPEC.md).

2. **Missing DynamoDB Tables**:
   - `SagaRuns`, `SagaSteps`, and `SagaTrace` are specified in SPEC.md §3.2 but are not created in `setup.ps1`.
   - *Resolution*: `infra/provision.py` must idempotently create these three tables and ensure `SagaLeases` has key `sagaId`.

3. **EventBridge Buses**:
   - `setup.ps1` creates a single bus `saga-bus`.
   - SPEC.md D10 requires dedicated buses `saga-bus-b`, `saga-bus-c`, and `saga-bus-d` to isolate paths and measure coupling cleanly.
   - *Resolution*: `infra/provision.py` will create `saga-bus-b`, `saga-bus-c`, and `saga-bus-d`.

4. **Lambda Zip Packaging & Dependencies**:
   - `deploy-lambda.ps1` currently zips only the individual handler file.
   - Phase 1 refactoring introduces `common/` library modules used across all handlers.
   - *Resolution*: Packaging must include `common/` in the zip for each Lambda, and `deploy-lambda.ps1` must be updated accordingly in Phase 1.

5. **Lambda Timeout for Service Functions**:
   - Currently uses the AWS default timeout of 3 seconds.
   - SPEC.md Phase 4 requires timeout ≥ 60s for service functions (especially when acting as leader or watchers in Path D).
   - *Resolution*: Set `--timeout 60` during `create-function` / `update-function-configuration`.

6. **Input Payload Envelope**:
   - Handlers currently expect top-level `orderId` and `action`.
   - SPEC.md defines a comprehensive saga envelope (`sagaId`, `path`, `workload`, `payload`, etc.) and events coming from EventBridge wrap payload inside `detail`.
   - *Resolution*: Handlers will use `common/events.py: parse_event()` to accept either legacy direct invocations (`action`, `orderId`) or full envelopes and EventBridge event wrappers transparently, ensuring `test.ps1` never breaks.
