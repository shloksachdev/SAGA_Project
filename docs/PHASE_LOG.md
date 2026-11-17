<!--
Purpose: Phase execution log and evidence for spec acceptance verification.
Phase: Phase 0
-->

# Phase Execution Log

## Phase 0: Audit, LocalStack Spikes, Contracts, Repo Hygiene

### Goal
Replace assumptions with facts and freeze the contracts.

### Completed Tasks
1. **Repo Audit**: Read every file in the repo and generated `docs/REPO_AUDIT.md`.
2. **Repo Hygiene**:
   - Confirmed `.gitattributes` enforces LF across all environments.
   - Created `setup.sh` mirroring `setup.ps1` for POSIX/Bash environments.
   - Updated `.gitignore` with `results/raw/`, `__pycache__/`, `.pytest_cache/`, `build/`, `*.zip`.
3. **LocalStack Spikes**:
   - Implemented spikes `S1` through `S8` under `spikes/` and `spikes/run_all.py`.
   - Verified capabilities and documented findings and fallbacks in `docs/localstack_findings.md`.
4. **Contracts Materialized**:
   - `docs/CONTRACTS.md` (canonical contract specification from §3).
   - `contracts/envelope.schema.json` (JSON schema for the saga envelope).
   - `common/contracts.py` (TypedDicts, dataclasses, trace event-name constants).

---

### Evidence

#### 1. `python spikes/run_all.py` Output

```text
================================================================================
RUNNING PHASE 0 LOCALSTACK SPIKES (S1 - S8)
================================================================================

--- Running Spike S1: EventBridge rule -> Lambda delivers $.detail as Lambda event ---
[S1] Setting up resources...
[S1] Received event in Lambda: {'customMessage': 'hello_s1', 'orderId': 's1-100'}
[S1] PASS: EventBridge delivered $.detail directly to Lambda event.

--- Running Spike S2: Step Functions -> Lambda with named-error Catch and Retry (IntervalSeconds 1) ---
[S2] Setting up Lambda and State Machine...
[S2] Execution status: SUCCEEDED, output: {"outcome":"CAUGHT_NAMED"}
[S2] PASS: Step Functions caught named error 'CustomBusinessError' and honored Retry/Catch.

--- Running Spike S3: Step Functions putEvents service integration ---
[S3] Checking Step Functions putEvents service integration...
[S3] PASS: Step Functions putEvents service integration succeeded.

--- Running Spike S4: DynamoDB conditional UpdateItem with epoch increment ---
[S4] Setting up table for conditional lease test...
[S4] Test 1: First acquisition on non-existent item...
[S4] First acquisition succeeded.
[S4] Test 2: Competing acquisition while active (should fail)...
[S4] Competing acquisition failed with ConditionalCheckFailedException as expected.
[S4] Test 3: Takeover after expiry (simulated with future timestamp)...
[S4] Takeover succeeded: epoch=2, owner=node-2
[S4] PASS: Conditional UpdateItem with epoch increment functions correctly.

--- Running Spike S5: DynamoDB TransactWriteItems with ConditionCheck ---
[S5] Testing TransactWriteItems with ConditionCheck...
[S5] Valid transaction committed successfully.
[S5] Condition failure raised TransactionCanceledException as expected.
[S5] PASS: TransactWriteItems with ConditionCheck is fully supported.

--- Running Spike S6: Lambda invoking Lambda synchronously from inside container (4 concurrent) ---
[S6] Deploying worker and caller Lambdas...
[S6] Invoking caller Lambda...
[S6] Received results: [{'worker_status': 'OK', 'worker_id': 0}, {'worker_status': 'OK', 'worker_id': 1}, {'worker_status': 'OK', 'worker_id': 2}, {'worker_status': 'OK', 'worker_id': 3}]
[S6] PASS: Lambda successfully invoked 4 concurrent Lambdas from inside container.

--- Running Spike S7: EventBridge target RetryPolicy + DeadLetterConfig (SQS) ---
[S7] Setting up SQS DLQ, failing Lambda, and EventBridge rule...
[S7] FAIL: Event did not reach SQS DLQ (or target RetryPolicy/DLQ not supported).

--- Running Spike S8: sfn.get_execution_history returns state-entered events ---
[S8] Testing sfn.get_execution_history for state-entered events...
[S8] History event types found: ['ExecutionStarted', 'PassStateEntered', 'PassStateExited', 'PassStateEntered', 'PassStateExited', 'ExecutionSucceeded']
[S8] PASS: sfn.get_execution_history returns state-entered events.

================================================================================
SPIKE RESULTS SUMMARY TABLE
================================================================================
Spike  | Status | Verification Target                                | Fallback / Note
------------------------------------------------------------------------------------------------------------------------
S1     | PASS   | EventBridge rule -> Lambda delivers $.detail as Lambda event | Native behavior verified
S2     | PASS   | Step Functions -> Lambda with named-error Catch and Retry (IntervalSeconds 1) | Native behavior verified
S3     | PASS   | Step Functions putEvents service integration       | Native behavior verified
S4     | PASS   | DynamoDB conditional UpdateItem with epoch increment | Native behavior verified
S5     | PASS   | DynamoDB TransactWriteItems with ConditionCheck    | Native behavior verified
S6     | PASS   | Lambda invoking Lambda synchronously from inside container (4 concurrent) | Native behavior verified
S7     | FAIL   | EventBridge target RetryPolicy + DeadLetterConfig (SQS) | Adopt fallback: Implement retry-then-DLQ inside the Notification handler
S8     | PASS   | sfn.get_execution_history returns state-entered events | Native behavior verified
```

#### 2. `.\test.ps1` Output

```text
=== Deploying all 4 Lambda functions ===

-- Deploying Order --
=== Deploying Order ===
Zipping order_handler.py -> Order.zip ...
  OK: Order.zip created.
Function already exists -- updating code...
  OK: code updated.

=== Testing Order ===
Testing: forward action (action=create)
  OK: {"orderId": "order-123", "status": "ORDER_CREATED"}
Testing: compensating action (action=cancel)
  OK: {"orderId": "order-123", "status": "ORDER_CANCELLED"}

=== Order : DEPLOYED AND BOTH TESTS PASSED ===
  [DEPLOY OK] Order

-- Deploying Payment --
=== Deploying Payment ===
Zipping payment_handler.py -> Payment.zip ...
  OK: Payment.zip created.
Function already exists -- updating code...
  OK: code updated.

=== Testing Payment ===
Testing: forward action (action=charge)
  OK: {"orderId": "order-123", "status": "PAYMENT_COMPLETED"}
Testing: compensating action (action=compensate)
  OK: {"orderId": "order-123", "status": "PAYMENT_COMPENSATED"}

=== Payment : DEPLOYED AND BOTH TESTS PASSED ===
  [DEPLOY OK] Payment

-- Deploying Inventory --
=== Deploying Inventory ===
Zipping inventory_handler.py -> Inventory.zip ...
  OK: Inventory.zip created.
Function already exists -- updating code...
  OK: code updated.

=== Testing Inventory ===
Testing: forward action (action=reserve)
  OK: {"orderId": "order-123", "status": "INVENTORY_RESERVED"}
Testing: compensating action (action=release)
  OK: {"orderId": "order-123", "status": "INVENTORY_RELEASED"}

=== Inventory : DEPLOYED AND BOTH TESTS PASSED ===
  [DEPLOY OK] Inventory

-- Deploying Notification --
=== Deploying Notification ===
Zipping notification_handler.py -> Notification.zip ...
  OK: Notification.zip created.
Function already exists -- updating code...
  OK: code updated.

=== Testing Notification ===
Testing: forward action (action=notify)
  OK: {"orderId": "order-123", "status": "NOTIFICATION_SENT"}
Testing: compensating action (action=unnotify)
  OK: {"orderId": "order-123", "status": "NOTIFICATION_RETRACTED"}

=== Notification : DEPLOYED AND BOTH TESTS PASSED ===
  [DEPLOY OK] Notification

=== Re-verifying all 4 Lambda functions directly ===

-- Order --
  [PASS] create: {"orderId": "order-123", "status": "ORDER_CREATED"}
  [PASS] cancel: {"orderId": "order-123", "status": "ORDER_CANCELLED"}

-- Payment --
  [PASS] charge: {"orderId": "order-123", "status": "PAYMENT_COMPLETED"}
  [PASS] compensate: {"orderId": "order-123", "status": "PAYMENT_COMPENSATED"}

-- Inventory --
  [PASS] reserve: {"orderId": "order-123", "status": "INVENTORY_RESERVED"}
  [PASS] release: {"orderId": "order-123", "status": "INVENTORY_RELEASED"}

-- Notification --
  [PASS] notify: {"orderId": "order-123", "status": "NOTIFICATION_SENT"}
  [PASS] unnotify: {"orderId": "order-123", "status": "NOTIFICATION_RETRACTED"}

=== Summary ===
Re-verification: 8 / 8 direct invoke tests passed
All 4 Lambdas deployed successfully and all tests passed.
Exit code: 0
```

#### 3. `git status` Output

```text
On branch master
Your branch is up to date with 'origin/master'.

Changes not staged for commit:
	modified:   .gitignore

Untracked files:
	SPEC.md
	common/
	contracts/
	docs/
	setup.sh
	spikes/
```


---

## Phase 1: Shared Foundation

### Goal
One common library so all paths run the same step logic and emit identical measurements.

### Completed Tasks
1. `common/aws.py`: Boto3 client/resource factory matching the existing Lambda/host endpoint and credential patterns.
2. `common/policy.py`: System-wide retry (`COMP_MAX_ATTEMPTS=3`, `COMP_INTERVAL_MS=1000`) and lease timing constants (`LEASE_TTL_MS=5000`, `HEARTBEAT_MS=1666`, `WATCH_MAX_ROUNDS=4`, `WATCH_JITTER_MS=300`).
3. `common/workloads.py`: Workload configuration and step dependency declarations for `order` workflow (Order `["*"]`, Payment `[]`, Inventory `[]`, Notification `[]`).
4. `common/work.py`: `do_work(ms, jitter, scale)` with `workScale=0` zero-sleep fast path (D4) and structured/legacy fault injection evaluation (`apply_faults`).
5. `common/steps.py`: Idempotent step state machine over `SagaSteps` and `SagaRuns`:
   - `begin_forward` with duplicate delivery protection (`ALREADY_DONE`).
   - `complete_forward` with atomic sequence counter (`seq`).
   - `fail_forward` marking failed step and saga state.
   - `begin_compensation` (COMPLETED -> COMPENSATING, increments `compInvocations`, NOOP on duplicate/uncompleted).
   - `complete_compensation` (COMPENSATING -> COMPENSATED, increments `compApplied` exactly once).
6. `common/trace.py`: Append-only distributed trace emitter to `SagaTrace` table.
7. `common/metered.py`: Operation counting wrapper (`DDB_OPS`, `EVENTS_PUT`, `LAMBDA_END`).
8. Refactored service handlers (`order_handler.py`, `payment_handler.py`, `inventory_handler.py`, `notification_handler.py`) via `common/handler_helper.py` preserving full backward compatibility.
9. `infra/provision.py`: Idempotent provisioning of `SagaRuns`, `SagaSteps`, `SagaTrace`, `SagaLeases` (keyed on `sagaId`), and buses `saga-bus-b/c/d`. Called from `setup.ps1` and `setup.sh`.
10. `deploy-lambda.ps1`: Extended to package `common/` into each Lambda deployment zip (`infra/package.py`) and wait for `Active` state before invoking.

---

### Evidence

#### 1. `pytest tests/phase1 -q` Output

```text
......                                                                   [100%]
============================== warnings summary ===============================
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\dateutil\tz\tz.py:37
  C:\Users\shlok\AppData\Local\Programs\Python\Python312\Lib\site-packages\dateutil\tz\tz.py:37: DeprecationWarning: datetime.datetime.utcfromtimestamp() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.fromtimestamp(timestamp, datetime.UTC).
    EPOCH = datetime.datetime.utcfromtimestamp(0)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
6 passed, 1 warning in 184.31s (0:03:04)
```

Verified scenarios:
- (a) `test_forward_invoked_twice_applies_once`: PASS
- (b) `test_compensation_non_completed_step_returns_noop`: PASS
- (c) `test_compensation_twice_yields_correct_counts` (`compApplied == 1`, `compInvocations == 2`): PASS
- (d) `test_work_scale_zero_runs_without_sleeping`: PASS
- (e) `test_faults_named_errors` (`PaymentDeclined`, `InventoryShortage`, `simulateFailure`): PASS
- Direct invocation of all 4 handlers with `SagaEnvelope` producing `SagaSteps` and `SagaTrace` rows: PASS

#### 2. `.\setup.ps1` Idempotency Runs (Ran Twice)

Pass 1 exit code: 0
Pass 2 exit code: 0
Key tables (`Orders`, `SagaRuns`, `SagaSteps`, `SagaTrace`, `SagaLeases`) and buses (`saga-bus`, `saga-bus-b`, `saga-bus-c`, `saga-bus-d`) verified intact and verified twice with zero errors.

#### 3. `.\test.ps1` Output

```text
=== Deploying all 4 Lambda functions ===

-- Deploying Order --
=== Deploying Order ===
Zipping order_handler.py and common/ -> Order.zip ...
[package] Built Order.zip with handler order_handler.py and common/ package.
  OK: Order.zip created.
Function doesn't exist yet -- creating...
  OK: function created.

=== Testing Order ===
Testing: forward action (action=create)
  OK: {"orderId": "order-123", "status": "ORDER_CREATED"}
Testing: compensating action (action=cancel)
  OK: {"orderId": "order-123", "status": "ORDER_CANCELLED"}

=== Order : DEPLOYED AND BOTH TESTS PASSED ===
  [DEPLOY OK] Order

-- Deploying Payment --
=== Deploying Payment ===
Zipping payment_handler.py and common/ -> Payment.zip ...
[package] Built Payment.zip with handler payment_handler.py and common/ package.
  OK: Payment.zip created.
Function doesn't exist yet -- creating...
  OK: function created.

=== Testing Payment ===
Testing: forward action (action=charge)
  OK: {"orderId": "order-123", "status": "PAYMENT_COMPLETED"}
Testing: compensating action (action=compensate)
  OK: {"orderId": "order-123", "status": "PAYMENT_COMPENSATED"}

=== Payment : DEPLOYED AND BOTH TESTS PASSED ===
  [DEPLOY OK] Payment

-- Deploying Inventory --
=== Deploying Inventory ===
Zipping inventory_handler.py and common/ -> Inventory.zip ...
[package] Built Inventory.zip with handler inventory_handler.py and common/ package.
  OK: Inventory.zip created.
Function doesn't exist yet -- creating...
  OK: function created.

=== Testing Inventory ===
Testing: forward action (action=reserve)
  OK: {"orderId": "order-123", "status": "INVENTORY_RESERVED"}
Testing: compensating action (action=release)
  OK: {"orderId": "order-123", "status": "INVENTORY_RELEASED"}

=== Inventory : DEPLOYED AND BOTH TESTS PASSED ===
  [DEPLOY OK] Inventory

-- Deploying Notification --
=== Deploying Notification ===
Zipping notification_handler.py and common/ -> Notification.zip ...
[package] Built Notification.zip with handler notification_handler.py and common/ package.
  OK: Notification.zip created.
Function doesn't exist yet -- creating...
  OK: function created.

=== Testing Notification ===
Testing: forward action (action=notify)
  OK: {"orderId": "order-123", "status": "NOTIFICATION_SENT"}
Testing: compensating action (action=unnotify)
  OK: {"orderId": "order-123", "status": "NOTIFICATION_RETRACTED"}

=== Notification : DEPLOYED AND BOTH TESTS PASSED ===
  [DEPLOY OK] Notification

=== Re-verifying all 4 Lambda functions directly ===

-- Order --
  [PASS] create: {"orderId": "order-123", "status": "ORDER_CREATED"}
  [PASS] cancel: {"orderId": "order-123", "status": "ORDER_CANCELLED"}

-- Payment --
  [PASS] charge: {"orderId": "order-123", "status": "PAYMENT_COMPLETED"}
  [PASS] compensate: {"orderId": "order-123", "status": "PAYMENT_COMPENSATED"}

-- Inventory --
  [PASS] reserve: {"orderId": "order-123", "status": "INVENTORY_RESERVED"}
  [PASS] release: {"orderId": "order-123", "status": "INVENTORY_RELEASED"}

-- Notification --
  [PASS] notify: {"orderId": "order-123", "status": "NOTIFICATION_SENT"}
  [PASS] unnotify: {"orderId": "order-123", "status": "NOTIFICATION_RETRACTED"}

=== Summary ===
Re-verification: 8 / 8 direct invoke tests passed
All 4 Lambdas deployed successfully and all tests passed.
Exit code: 0
```

#### 4. `git status` Output

```text
On branch master
Your branch is up to date with 'origin/master'.

Changes not staged for commit:
	modified:   .gitignore
	modified:   deploy-lambda.ps1
	modified:   inventory_handler.py
	modified:   notification_handler.py
	modified:   order_handler.py
	modified:   payment_handler.py
	modified:   setup.ps1

Untracked files:
	SPEC.md
	common/
	conftest.py
	contracts/
	docs/
	infra/
	pytest.ini
	setup.sh
	spikes/
	tests/
```


---

## Phase 2: Path A (Pure Orchestration)

### Goal
A Step Functions state machine that runs the saga and compensates as a sequential reverse chain.

### Completed Tasks
1. `paths/a/build_asl.py`: Programmatically generates ASL state machine definition from `WorkloadConfig`.
   - Forward: `Order -> Payment -> Inventory -> Notification -> SagaSuccess`.
   - Catch: Each forward task Catches `States.ALL` with `"ResultPath": "$.error"` and routes to the compensation task of the step completed immediately prior.
   - Compensation: Sequential reverse chain (`Compensate_Notification -> Compensate_Inventory -> Compensate_Payment -> Compensate_Order -> Compensated`).
   - Retries: `COMP_MAX_ATTEMPTS=3`, `IntervalSeconds=1`, `BackoffRate=1.0` per `common/policy.py`.
2. `paths/a/deploy.py`: Idempotent state machine provisioning (`create_state_machine` or `update_state_machine`).
3. `paths/a/run.py`: Initiates saga execution, emits `SAGA_STARTED`, records initial `SagaRuns` item, and polls execution until terminal state.
4. Integrated `paths/a/deploy.py` into `infra/provision.py` provisioning pipeline.
5. Handlers raise named exceptions on failure in Path A per D13; `SAGA_COMPLETED` written by Notification handler, and `SAGA_COMPENSATED` written by Order cancel handler upon completing rollback.

---

### Evidence

#### 1. `pytest tests/phase2 -q` Output

```text
......                                                                   [100%]
============================== warnings summary ===============================
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\dateutil\tz\tz.py:37
  C:\Users\shlok\AppData\Local\Programs\Python\Python312\Lib\site-packages\dateutil\tz\tz.py:37: DeprecationWarning: datetime.datetime.utcfromtimestamp() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.fromtimestamp(timestamp, datetime.UTC).
    EPOCH = datetime.datetime.utcfromtimestamp(0)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
6 passed, 1 warning in 173.29s (0:02:53)
```

Verified scenarios:
- **Happy Path** (`test_happy_path_orchestration`): All 4 steps (Order, Payment, Inventory, Notification) COMPLETED; `SagaRuns.status == COMPLETED`; `SAGA_STARTED` and `SAGA_COMPLETED` in trace: **PASS**
- **Payment Failure** (`test_failure_at_payment`): Exactly Order compensated (`compApplied == 1`); Payment `status == FAILED` (not compensated); Inventory and Notification never ran; `STEP_FAILED` precedes `SAGA_COMPENSATED`; `SagaRuns.status == COMPENSATED`: **PASS**
- **Inventory Failure** (`test_failure_at_inventory`): Payment and Order compensated in reverse order by `seq` (Payment compensated before Order); Inventory `status == FAILED`; `SagaRuns.status == COMPENSATED`: **PASS**
- **Notification Failure** (`test_failure_at_notification`): Inventory, Payment, Order all compensated in reverse order (`compensatedAt` ordering verified); Notification `status == FAILED`; `SagaRuns.status == COMPENSATED`: **PASS**
- **Transient Compensation Failure Retry** (`test_transient_compensation_failure_with_retry`): `compFailFirstN=1` on Order; Step Functions retried compensation; `COMP_FAILED_ATTEMPT` recorded in trace; run ends `COMPENSATED`; Order `compApplied == 1`, `compInvocations == 2`: **PASS**
- **Duplicate-Safe Compensation** (`test_duplicate_safe_compensation`): Direct second invocation of compensation task leaves `compApplied == 1`: **PASS**

#### 2. `.\test.ps1` Regression Run

```text
=== Re-verifying all 4 Lambda functions directly ===
-- Order --
  [PASS] create: {"orderId": "order-123", "status": "ORDER_CREATED"}
  [PASS] cancel: {"orderId": "order-123", "status": "ORDER_CANCELLED"}
-- Payment --
  [PASS] charge: {"orderId": "order-123", "status": "PAYMENT_COMPLETED"}
  [PASS] compensate: {"orderId": "order-123", "status": "PAYMENT_COMPENSATED"}
-- Inventory --
  [PASS] reserve: {"orderId": "order-123", "status": "INVENTORY_RESERVED"}
  [PASS] release: {"orderId": "order-123", "status": "INVENTORY_RELEASED"}
-- Notification --
  [PASS] notify: {"orderId": "order-123", "status": "NOTIFICATION_SENT"}
  [PASS] unnotify: {"orderId": "order-123", "status": "NOTIFICATION_RETRACTED"}

=== Summary ===
Re-verification: 8 / 8 direct invoke tests passed
All 4 Lambdas deployed successfully and all tests passed.
Exit code: 0
```

#### 3. `pytest tests/phase1 -q` Regression Run

```text
6 passed, 1 warning in 172.05s (0:02:52)
Exit code: 0
```

---

## Phase 3: Path B (Pure Choreography)

### Goal
EventBridge-only saga with a reverse event chain for compensation (D9, D10).

### Completed Tasks
1. `paths/b/provision.py`:
   - Programmatically deployed 4 forward rules on `saga-bus-b`:
     - `path-b-fwd-order` matching `detail-type: ["SagaStarted"]` -> `Order` Lambda
     - `path-b-fwd-payment` matching `source: ["saga.order"]`, `detail-type: ["OrderCreated"]` -> `Payment` Lambda
     - `path-b-fwd-inventory` matching `source: ["saga.payment"]`, `detail-type: ["PaymentCharged"]` -> `Inventory` Lambda
     - `path-b-fwd-notification` matching `source: ["saga.inventory"]`, `detail-type: ["InventoryReserved"]` -> `Notification` Lambda
   - Programmatically deployed 3 reverse compensation rules (D9 reverse chain) on `saga-bus-b`:
     - `path-b-comp-inventory` matching `source: ["saga.notification"]`, `detail-type: ["NotificationFailed", "NotificationCompensated"]` -> `Inventory` Lambda
     - `path-b-comp-payment` matching `source: ["saga.inventory"]`, `detail-type: ["InventoryFailed", "InventoryCompensated"]` -> `Payment` Lambda
     - `path-b-comp-order` matching `source: ["saga.payment"]`, `detail-type: ["PaymentFailed", "PaymentCompensated"]` -> `Order` Lambda
   - Configured `InputPath: "$.detail"` on each target and added `lambda:InvokeFunction` permissions with principal `events.amazonaws.com`.
2. Handlers in Path B:
   - Perform action, update `SagaSteps`, publish result events (`OrderCreated`, `PaymentCharged`, `InventoryReserved`, `NotificationSent`, `PaymentFailed`, `InventoryFailed`, `NotificationFailed`, `PaymentCompensated`, `InventoryCompensated`, `OrderCancelled`).
   - Business failures return normally after publishing failure events (D13).
   - Final forward step (`Notification`) emits `SAGA_COMPLETED` and marks `SagaRuns.status = COMPLETED`.
   - Final compensation step (`Order cancel`) emits `SAGA_COMPENSATED` and marks `SagaRuns.status = COMPENSATED`.
3. `paths/b/run.py`:
   - Emits `SAGA_STARTED`, initializes `SagaRuns` item, and publishes `SagaStarted` with `detail["action"] = "forward"` to `saga-bus-b`.
   - Polls `SagaRuns` until terminal state (`COMPLETED`, `COMPENSATED`, `COMPENSATION_FAILED`) or timeout (60 s).
4. In-handler compensation retry loop (Task 4):
   - Implemented inside `common/handler_helper.py` using `COMP_INTERVAL_MS=1000` and `COMP_MAX_ATTEMPTS=3`.
   - On retry attempt, increments `compInvocations` in `SagaSteps` and records `COMP_FAILED_ATTEMPT`.
5. Provisioning integration:
   - Wired `paths/b/provision.py` into `infra/provision.py`.

---

### Evidence

#### 1. `pytest tests/phase3 -q` Output

```text
......                                                                   [100%]
============================== warnings summary ===============================
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\dateutil\tz\tz.py:37
  C:\Users\shlok\AppData\Local\Programs\Python\Python312\Lib\site-packages\dateutil\tz\tz.py:37: DeprecationWarning: datetime.datetime.utcfromtimestamp() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.fromtimestamp(timestamp, datetime.UTC).
    EPOCH = datetime.datetime.utcfromtimestamp(0)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
6 passed, 1 warning in 157.52s (0:02:37)
```

Verified scenarios:
- **Happy Path** (`test_happy_path_choreography`): All 4 steps (Order, Payment, Inventory, Notification) COMPLETED via EventBridge bus `saga-bus-b`; `SagaRuns.status == COMPLETED`; `SAGA_STARTED` and `SAGA_COMPLETED` in trace: **PASS**
- **Payment Failure** (`test_failure_at_payment`): Exactly Order compensated (`compApplied == 1`); Payment `status == FAILED` (not compensated); Inventory and Notification never ran; `STEP_FAILED` precedes `SAGA_COMPENSATED`; `SagaRuns.status == COMPENSATED`: **PASS**
- **Inventory Failure** (`test_failure_at_inventory`): Payment and Order compensated in reverse order by `seq` via reverse event chain; Inventory `status == FAILED`; `SagaRuns.status == COMPENSATED`: **PASS**
- **Notification Failure** (`test_failure_at_notification`): Inventory, Payment, Order all compensated in reverse order (`compensatedAt` ordering verified); Notification `status == FAILED`; `SagaRuns.status == COMPENSATED`: **PASS**
- **Transient Compensation Failure Retry** (`test_transient_compensation_failure_with_retry`): `compFailFirstN=1` on Order; in-handler compensation retry loop succeeded; `COMP_FAILED_ATTEMPT` recorded in trace; run ends `COMPENSATED`; Order `compApplied == 1`, `compInvocations == 2`: **PASS**
- **Duplicate Event Delivery** (`test_duplicate_event_delivery`): Duplicate delivery of `PaymentFailed` event leaves `compApplied == 1` and emits `COMP_DUPLICATE_IGNORED`: **PASS**

#### 2. Full Regression Run (`pytest tests/phase1 tests/phase2 tests/phase3 -q`)

```text
..................                                                       [100%]
============================== warnings summary ===============================
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\dateutil\tz\tz.py:37
  C:\Users\shlok\AppData\Local\Programs\Python\Python312\Lib\site-packages\dateutil\tz\tz.py:37: DeprecationWarning: datetime.datetime.utcfromtimestamp() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.fromtimestamp(timestamp, datetime.UTC).
    EPOCH = datetime.datetime.utcfromtimestamp(0)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
18 passed, 1 warning in 511.40s (0:08:31)
Exit code: 0
```

#### 3. `.\test.ps1` Regression Run

```text
=== Re-verifying all 4 Lambda functions directly ===
-- Order --
  [PASS] create: {"orderId": "order-123", "status": "ORDER_CREATED"}
  [PASS] cancel: {"orderId": "order-123", "status": "ORDER_CANCELLED"}
-- Payment --
  [PASS] charge: {"orderId": "order-123", "status": "PAYMENT_COMPLETED"}
  [PASS] compensate: {"orderId": "order-123", "status": "PAYMENT_COMPENSATED"}
-- Inventory --
  [PASS] reserve: {"orderId": "order-123", "status": "INVENTORY_RESERVED"}
  [PASS] release: {"orderId": "order-123", "status": "INVENTORY_RELEASED"}
-- Notification --
  [PASS] notify: {"orderId": "order-123", "status": "NOTIFICATION_SENT"}
  [PASS] unnotify: {"orderId": "order-123", "status": "NOTIFICATION_RETRACTED"}

=== Summary ===
Re-verification: 8 / 8 direct invoke tests passed
All 4 Lambdas deployed successfully and all tests passed.
Exit code: 0
```
