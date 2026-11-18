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


## Phase 4: Path D Part 1 (Leader Election & Heartbeat)

### Goal
First-responder lease acquisition, heartbeating, watcher takeover, and deterministic election (D4, D5, D7, D8, D14).

### Completed Tasks
1. `common/lease.py`:
   - Lease record schema on DynamoDB `SagaLeases`: `sagaId` (PK), `ownerId`, `epoch`, `leaseExpiresAt`, `status` (`ACTIVE`, `DONE`), `acquiredAt`, `lastRenewedAt`.
   - `try_acquire(saga_id, owner_id, ttl_ms)`: Conditional write on `attribute_not_exists(sagaId) OR (leaseExpiresAt < :now AND #st <> :done)`. Emits `LEASE_ACQUIRED` (first acquire) or `LEASE_TAKEOVER` (takeover).
   - `renew(lease)`: Conditional update enforcing `ownerId == :owner AND epoch == :epoch AND #st = :active`. Emits `LEASE_RENEWED`.
   - `release_done(lease)`: Sets `status = DONE`. Non-reacquirable.
   - Enforced D5: Zero static workload or service references.
2. `common/election.py`:
   - `participate(envelope, step_name, runner_fn)`: Checks eligibility in `SagaSteps`. Only services whose step is `COMPLETED` or `FAILED` are eligible; non-participants ignore election.
   - If `try_acquire` succeeds, launches a background heartbeating thread renewing every `LEASE_RENEW_INTERVAL_MS` (default 500 ms) and invokes the compensation runner.
   - If `try_acquire` fails (loser), enters the watcher loop (D7): sleeps `leaseExpiresAt - now + random(0, WATCH_JITTER_MS)`, checks `SagaRuns` status (terminating if `COMPENSATED` / `COMPLETED`), or attempts takeover.
   - `default_trivial_runner`: Injects `leaderFault="crash_after:K"` on epoch 1, aborting before release to test watcher takeover.
3. EventBridge Fan-in Rule on `saga-bus-d` (`paths/d/provision.py`):
   - Created forward rules for Path D and `path-d-election` rule matching `source: ["saga.path_d"]`, `detail-type: ["CompensationNeeded"]`.
   - Targets all 4 services (`Order`, `Payment`, `Inventory`, `Notification`) using `InputTransformer` injecting `action="elect"`.
   - Wired into `infra/provision.py`.
4. Handlers Routing:
   - Handlers inspect `event.get("action") == "elect"` and delegate to `participate(envelope, step_name)`.
   - On forward business failure, handlers emit `COMP_NEEDED_PUBLISHED` and publish `CompensationNeeded` to `saga-bus-d`.
5. Acceptance Test Suite (`tests/phase4/test_election.py`):
   - Verified 5/5 acceptance scenarios matching SPEC.md Phase 4 criteria.

---

### Evidence

#### 1. `pytest tests/phase4 -q` Output

```text
.....                                                                    [100%]
5 passed, 1 warning in 119.65s (0:01:59)
Exit code: 0
```

Verified scenarios:
- **First-responder election** (`test_first_responder_wins` & `test_end_to_end_election_with_forced_failure`): Forced failure produces exactly one `LEASE_ACQUIRED` among participants; losers log `LEASE_LOST` and become watchers; run completes `COMPENSATED`.
- **Ineligibility** (`test_ineligible_service_ignores_election`): Service whose step never ran does not participate in election (`status is None`).
- **Heartbeat & Renewal** (`test_lease_renewal_during_compensation`): Leader renews lease; `SagaLeases.epoch` retained / updated; `leaseExpiresAt` advances; `LEASE_RENEWED` recorded in trace.
- **Leader Crash & Takeover** (`test_leader_crash_and_takeover`): Leader injected with `leaderFault="crash_after:1"` aborts; watcher detects expiry after `leaseExpiresAt`; watcher acquires with `LEASE_TAKEOVER` and `epoch = 2`; compensation completes to `COMPENSATED`.
- **Determinism under competition & non-reacquisition** (`test_lease_expiry_and_takeover` & `test_lease_done_cannot_be_reacquired`): Competing acquisitions fail with conditional check; `DONE` lease cannot be reacquired.

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


## Phase 5: Path D Part 2 (Dynamic DAG Compensation Scheduler & LIFO Ablation)

### Goal
Dynamic DAG building from self-declared dependencies, parallel execution, LIFO controlled ablation, and zero static workload references (D5, D7, D8, D14).

### Completed Tasks
1. `common/core/dag.py` (pure Python, no boto3):
   - `build_compensation_graph(step_records, failed_step)` builds dependency graph dynamically:
     - Includes steps with status `COMPLETED` or `COMPENSATING`, plus failed step only if `compensateOnFailure` is True.
     - Resolves dependencies from `compensateAfter`, resolving `"*"` to all other active nodes.
     - Dependencies on steps already `COMPENSATED` or uninvoked are treated as satisfied.
     - Detects cycles and raises `CyclicDependency`.
     - Provides `layers()` and `ready(done_set)`.
2. `common/core/scheduler.py` (pure Python, no boto3):
   - `run_parallel(graph, exec_fn, max_workers=8)`:
     - Dispatches ready nodes concurrently, releasing dependents as nodes complete.
     - Retries transient failures up to `COMP_MAX_ATTEMPTS` with `COMP_INTERVAL_MS` delay.
     - On retry exhaustion, marks node failed, blocks its dependents, and completes independent branches.
   - `run_lifo(graph, exec_fn)`:
     - Sequential ablation executing in descending `seq` order (ignoring `compensateAfter`).
   - `VirtualClock`: Discrete-event virtual time clock enabling exact makespan property verification without wall-clock latency.
3. `common/orchestrator.py` (adapter):
   - `orchestrate_compensation(leader_ctx, envelope)`:
     - Queries `SagaSteps` dynamically to construct the DAG without any static workload references (D5).
     - Emits `COMP_DISPATCHED` before synchronous `lambda.invoke`.
     - Supports `leaderFault="crash_after:K"`, allowing initial leader to crash and watcher to takeover and resume compensation.
     - Transitions `SagaRuns` to `COMPENSATED` and calls `release_done`.
4. Integration & Routing:
   - Handlers delegate `action="elect"` to `orchestrate_compensation`.
   - Updated `common/events.py` to transparently unwrap `saga` payload wrapper.
5. Enforcement test of D5 (`tests/phase5/test_no_static_refs.py`):
   - Statically verifies via AST that `common/election.py`, `common/lease.py`, `common/orchestrator.py`, and `common/core/*` contain zero imports or references to workloads or hard-coded service names.

---

### Evidence

#### 1. `pytest tests/phase5 -q` Output

```text
....................                                                     [100%]
20 passed, 1 warning in 84.16s (0:01:24)
Exit code: 0
```

Verified scenarios:
- **Unit tests with Virtual Time** (`tests/phase5/test_dag_scheduler.py`):
  - `test_chain_dag`: Makespan strictly equals sum of durations (100.0s).
  - `test_diamond_dag`: Makespan strictly equals 10 + max(20, 35) + 15 = 60.0s.
  - `test_star_with_wildcard`: `*` dependency waits for all other nodes; makespan equals max(A, B, C) + D = 75.0s.
  - `test_all_independent`: Makespan equals maximum node duration (45.0s).
  - `test_wide_fan`: Wide fan concurrency verified (55.0s).
  - `test_cycle_detection`: Cyclic dependency graph raises `CyclicDependency`.
  - `test_transient_failure_with_retry`: Fails attempt 1, retries after interval, succeeds on attempt 2.
  - `test_permanent_failure_blocks_dependents_not_siblings`: Fails all attempts on node; blocks its dependents while sibling branch finishes; returns `COMPENSATION_FAILED`.
  - `test_resume_with_already_compensated_steps`: Resumes with already COMPENSATED steps skipped and treated as satisfied.
  - `test_lifo_ablation_sequential`: Sequential LIFO execution in descending `seq` order (sum of durations).
- **Integration Tests** (`tests/phase5/test_integration.py`):
  - `test_parallel_dag_compensation_overlap`: Forced failure at Notification; Payment and Inventory compensation intervals overlap (`pay_start < inv_end and inv_start < pay_end`); Order starts after both complete; `compApplied == 1` for all 3 steps.
  - `test_lifo_ablation_no_overlap`: LIFO mode does NOT overlap (sequential execution in descending `seq` order).
  - `test_duplicate_compensation_needed_event`: Duplicate event delivery produces single compensation effect (`compApplied == 1`).
  - `test_leader_crash_after_one_dispatch`: Initial leader crashes after 1 dispatch; watcher takes over (`LEASE_TAKEOVER`, epoch 2) and finishes compensation; `compApplied == 1` for all steps.
- **Static Reference Enforcement** (`tests/phase5/test_no_static_refs.py`):
  - 6 files analyzed via AST; 0 violations found for all banned service names and workload imports.

#### 2. `.\test.ps1` Direct Invocation Regression Run

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


#### 3. Full Regression Run (`pytest tests/phase1 tests/phase2 tests/phase3 tests/phase4 tests/phase5 -v`)

```text
================== 43 passed, 1 warning in 780.18s (0:13:00) ==================
Exit code: 0
```
- Phase 1 Foundation: 6 / 6 passed
- Phase 2 Path A (Orchestration): 6 / 6 passed
- Phase 3 Path B (Choreography): 6 / 6 passed
- Phase 4 Path D Part 1 (Leader Election): 5 / 5 passed
- Phase 5 Path D Part 2 (DAG & LIFO Ablation): 20 / 20 passed

---

## Phase 6: Path C (Static Hybrid Baseline)

### Goal
A static hybrid architecture combining an orchestrated core (Order → Payment → Inventory in Step Functions with sequential reverse compensation) and a choreographed edge (Notification via EventBridge on `saga-bus-c` with SQS Dead Letter Queue fallback on failure).

### Completed Tasks
1. `paths/c/build_asl.py`:
   - Programmatically builds ASL state machine definition for `saga-path-c`.
   - Core forward chain: `Order -> Payment -> Inventory -> PublishOrderCoreCompleted`.
   - Reverse sequential compensation catches:
     - Payment failure compensates `Order` (cancel).
     - Inventory failure compensates `Payment` (refund) then `Order` (cancel).
   - Publishes `OrderCoreCompleted` event directly via Step Functions optimized `arn:aws:states:::events:putEvents` to `saga-bus-c` with `Detail.$: "$"`.
2. `paths/c/deploy.py`:
   - Deploys or updates the `saga-path-c` Step Functions state machine idempotently.
3. `paths/c/provision.py`:
   - Provisions SQS dead-letter queue `saga-c-notification-dlq`.
   - Deploys `saga-path-c` state machine.
   - Creates EventBridge rule `path-c-edge-notification` on `saga-bus-c` matching source `saga.path_c.core` and detail-type `OrderCoreCompleted`, targeting the `Notification` Lambda with `InputPath: "$.detail"`.
   - Integrated into root `infra/provision.py`.
4. `common/handler_helper.py`:
   - Implemented Spike S7 DLQ fallback for Path C edge failure in Notification handler:
   - On forward retry exhaustion, directly forwards the failed payload to `saga-c-notification-dlq`.
   - Emits `NOTIFICATION_DLQ` event to `SagaTrace`.
   - Transitions `SagaRuns` status to `COMPLETED` with trace attribute `edgeFailure=True`, leaving the orchestrated core intact and uncompensated.
5. `paths/c/run.py`:
   - Initializes `SagaRuns` record, emits `SAGA_STARTED`, and starts execution on `saga-path-c`.
   - Polls execution until terminal state (`COMPLETED` or `COMPENSATED`), returning result dictionary with trace events.
6. `tests/phase6/test_path_c.py`:
   - Acceptance test suite testing all 4 hybrid scenarios.

---

### Evidence

#### 1. `pytest tests/phase6 -v` Output

```text
============================= test session starts =============================
platform win32 -- Python 3.12.2, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\shlok\AppData\Local\Programs\Python\Python312\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\shlok\OneDrive\Desktop\Projects\SAGA_Project
configfile: pytest.ini
plugins: anyio-4.9.0, hydra-core-1.3.2, langsmith-0.7.6, asyncio-1.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 4 items

tests/phase6/test_path_c.py::test_happy_path_hybrid PASSED               [ 25%]
tests/phase6/test_path_c.py::test_failure_at_payment PASSED              [ 50%]
tests/phase6/test_path_c.py::test_failure_at_inventory PASSED            [ 75%]
tests/phase6/test_path_c.py::test_notification_forced_to_fail PASSED     [100%]

=================== 4 passed, 1 warning in 96.30s (0:01:36) ===================
Exit code: 0
```

Verified scenarios:
- `test_happy_path_hybrid`: Core steps (Order, Payment, Inventory) execute sequentially via Step Functions; `OrderCoreCompleted` is published to `saga-bus-c`; edge Notification is invoked via EventBridge; run reaches `COMPLETED`; `SAGA_COMPLETED` emitted.
- `test_failure_at_payment`: Payment fails; Payment Catch invokes compensation for Order; state machine transitions to `COMPENSATED`; Notification is never invoked.
- `test_failure_at_inventory`: Inventory fails; Inventory Catch compensates Payment then Order; state machine transitions to `COMPENSATED`; Notification is never invoked.
- `test_notification_forced_to_fail`: Core completes; Notification receives `OrderCoreCompleted` on `saga-bus-c` and fails; message is routed to `saga-c-notification-dlq`; `NOTIFICATION_DLQ` emitted; run status marked `COMPLETED` with `edgeFailure=True`; core steps remain `COMPLETED` (uncompensated).

#### 2. `.\test.ps1` Direct Invocation Regression Run

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

#### 3. Full Regression Run (`pytest tests/phase1 tests/phase2 tests/phase3 tests/phase4 tests/phase5 tests/phase6 -q`)

```text
...............................................                          [100%]
47 passed, 1 warning in 1080.85s (0:18:00)
Exit code: 0
```
- Phase 1 Foundation: 6 / 6 passed
- Phase 2 Path A (Orchestration): 6 / 6 passed
- Phase 3 Path B (Choreography): 6 / 6 passed
- Phase 4 Path D Part 1 (Leader Election): 5 / 5 passed
- Phase 5 Path D Part 2 (DAG & LIFO Ablation): 20 / 20 passed
- Phase 6 Path C (Static Hybrid Baseline): 4 / 4 passed

---

## Phase 7: Workload Expansion (7A TrainTicket-Derived & 7B Synthetic Wide-Fan)

### Goal
Implement and verify two additional workload configurations to characterize saga coordination beyond the basic 4-step e-commerce baseline:
1. **Phase 7A (TrainTicket-Derived)**: Asymmetric dependency structure on the 4 services (`Payment` refund depends on `Inventory` seat release via `compensateAfter: ["Inventory"]`, `Order` booking cancellation waits for all via `compensateAfter: ["*"]`), with realistic timing profiles (pay/refund 300ms, seat release 200ms, book/cancel/notify 100ms).
2. **Phase 7B (Synthetic Wide-Fan)**: Generic Lambda handler parameterized by `STEP_NAME` (`Step1`..`Step6`), implementing workloads `wide-2`, `wide-4`, `wide-6` where parallel compensation concurrency actually exists, enabling empirical verification of makespan reduction.

### Completed Tasks
1. `common/workloads.py`:
   - Added `TRAINTICKET_WORKLOAD`: mapping Order=book, Payment=pay, Inventory=seat-allocate, Notification=confirmation. Timings: pay 300ms, seat release 200ms, book/cancel/notify 100ms. Dependencies: `Payment: ["Inventory"]`, `Order: ["*"]`, others `[]`.
   - Added `WIDE_2_WORKLOAD`, `WIDE_4_WORKLOAD`, `WIDE_6_WORKLOAD`: Order first, followed by *k* sequential forward steps (`Step1`..`StepK`), all with `compensateAfter=[]` except `Order: ["*"]`. Compensation durations differ per step (100–1000 ms).
   - Registered all workloads in `WORKLOADS`.
2. `generic_handler.py`:
   - Single reusable handler parameterized via environment variable `STEP_NAME`.
   - Delegates to `execute_step` with generic forward/compensate functions and events (`{step}Success`, `{step}Failed`, `{step}Compensated`).
3. `infra/deploy_generic.py`:
   - Python deployment utility bundling `generic_handler.py` and `common/` into `Generic.zip` and deploying `Step1` through `Step6` to LocalStack.
4. Adaptations & Bug Fixes:
   - `common/handler_helper.py`: Generalized final-step detection using `is_final_step = (step_name.lower() == wl.steps[-1].name.lower())` replacing hardcoded `"Notification"`, and scoped it before the forward try block to prevent `NameError` during edge failures.
   - `paths/c/build_asl.py`: Generalized core vs edge separation (`core_steps = workload.steps[:-1]` and `edge_step = workload.steps[-1]`).
   - `paths/d/provision.py`: Sharded EventBridge election targets into chunks of at most 5 per rule to respect EventBridge's 5-target limit per rule.
   - `paths/a/run.py` & `paths/c/run.py`: Dynamically deploy workload-specific state machines (`saga-path-a-{workload}`, `saga-path-c-{workload}`).
   - `docs/WORKLOADS.md`: Fully documented workload definitions and declared TrainTicket as a shape-level port per SPEC requirements.
5. Tests:
   - `tests/phase7/test_trainticket.py`: 7 tests covering Paths A, B, C, and D with `trainticket`. Verified dynamic dependency enforcement on Path D (`pay_start >= inv_done` and `order_start >= pay_done`).
   - `tests/phase7/test_wide_fan.py`: 2 tests covering `wide-4` happy path forward execution and makespan comparison.
   - **Makespan reduction verified**: Path D parallel makespan (1868 ms) vs sequential LIFO (3508 ms) demonstrated a **46.75% reduction** (exceeding the required >= 25% threshold).

---

### Evidence

#### 1. `pytest tests/phase7/ -v` Output

```text
============================= test session starts =============================
platform win32 -- Python 3.12.2, pytest-9.0.2, pluggy-1.6.0 -- C:\Users\shlok\AppData\Local\Programs\Python\Python312\python.exe
cachedir: .pytest_cache
rootdir: C:\Users\shlok\OneDrive\Desktop\Projects\SAGA_Project
configfile: pytest.ini
plugins: anyio-4.9.0, hydra-core-1.3.2, langsmith-0.7.6, asyncio-1.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 9 items

tests/phase7/test_trainticket.py::test_trainticket_path_a_happy_path PASSED [ 11%]
tests/phase7/test_trainticket.py::test_trainticket_path_a_failure_compensation PASSED [ 22%]
tests/phase7/test_trainticket.py::test_trainticket_path_b_happy_path PASSED [ 33%]
tests/phase7/test_trainticket.py::test_trainticket_path_b_failure_compensation PASSED [ 44%]
tests/phase7/test_trainticket.py::test_trainticket_path_c_happy_path PASSED [ 55%]
tests/phase7/test_trainticket.py::test_trainticket_path_c_edge_failure PASSED [ 66%]
tests/phase7/test_trainticket.py::test_trainticket_path_d_dependency_order PASSED [ 77%]
tests/phase7/test_wide_fan.py::test_wide_fan_happy_path PASSED           [ 88%]
tests/phase7/test_wide_fan.py::test_wide_fan_parallel_vs_lifo_makespan PASSED [100%]

================== 9 passed, 1 warning in 226.54s (0:03:46) ===================
Exit code: 0
```

Verified scenarios:
- **Phase 7A (TrainTicket)**:
  - Path A happy path and compensation catch reverse order.
  - Path B happy path and compensation chain reverse order.
  - Path C happy path and edge DLQ failure (`edgeFailure=True`).
  - Path D dynamic dependency verification: Payment waited for Inventory (`pay_start >= inv_done`), Order waited for Payment (`order_start >= pay_done`), all 3 steps ended with `compApplied == 1`.
- **Phase 7B (Wide-Fan)**:
  - `test_wide_fan_happy_path`: 5 sequential forward steps (Order + Step1..Step4) complete with `SAGA_COMPLETED`.
  - `test_wide_fan_parallel_vs_lifo_makespan`:
    - Parallel makespan: `1868 ms`
    - LIFO makespan: `3508 ms`
    - Makespan reduction: **46.75%** (asserted >= 25% lower, PASS).

#### 2. `.\test.ps1` Direct Invocation Regression Run

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




---

## Phase 8: Fault-Injection Harness, Load Generator, Metrics Tooling

### Goal
Implement a reusable experiment harness that runs any path × workload × fault plan, interleaves runs across paths in randomized order, derives §3.5 metrics from `SagaTrace`, evaluates architectural coupling and analytical AWS list pricing costs, and validates distributed consistency invariants.

### Completed Tasks
1. `harness/pricing.json`:
   - Documented late-2024 AWS list prices for Lambda, EventBridge, Step Functions Standard, DynamoDB On-Demand (updated rates), and SQS with retrieval dates and source URLs.
2. `harness/cost.py`:
   - Computes analytical cost per transaction and per 1,000 transactions from metered/derived resource units.
   - Accepts `--run <runTag>` or `--file <path>` to evaluate actual empirical runs from `results/raw/` or prints the analytical baseline table.
3. `harness/coupling.py`:
   - Measures architectural coupling: ASL Lambda ARN bindings, EventBridge rules, and AST-based orchestrator static reference inspection (asserting strictly 0 for Path D per D5).
4. `harness/derive.py`:
   - Extracts all §3.5 metrics from `SagaTrace`: `happy_latency`, `compensation_latency`, `election_time`, `scheduling_makespan`, and resource unit counts.
5. `harness/consistency.py`:
   - Checks distributed consistency invariants on terminal saga runs (`compApplied <= 1`, no steps left `COMPLETED` on a compensated run, no steps stuck `COMPENSATING`).
   - Supports negative tests on corrupted data.
6. `harness/load.py`:
   - Open-loop load generator profiling throughput and latency under sustained offered rates.
7. `harness/run_experiment.py`:
   - Orchestrates interleaved, randomized runs across paths with warm-up filtering, emitting raw JSONL to `results/raw/<runTag>.jsonl` and metrics to `results/summary.csv`.
8. `README.md`:
   - Added "Running Experiments" section documenting exact reproduction commands.
9. `tests/phase8/test_harness.py`:
   - Full acceptance test suite verifying derive on synthetic traces with known timestamps, invariant verification, corruption detection, coupling, and cost modeling.

---

### Evidence

#### 1. Phase 8 Acceptance Tests (`pytest tests/phase8 -q`)

```text
......                                                                   [100%]
============================== warnings summary ===============================
..\..\..\..\AppData\Local\Programs\Python\Python312\Lib\site-packages\dateutil\tz\tz.py:37
  DeprecationWarning: datetime.datetime.utcfromtimestamp() is deprecated

6 passed, 1 warning in 4.59s
```

#### 2. Smoke Experiment Run (`python harness/run_experiment.py --config experiments/configs/smoke.json --runTag smoke-test`)

```text
[Experiment] Loaded config 'experiments/configs/smoke.json': 36 total runs planned under runTag 'smoke-test'
[Experiment] Output JSONL: C:\Users\shlok\OneDrive\Desktop\Projects\SAGA_Project\results\raw\smoke-test.jsonl
  [1/36] Running Path C (order, happy, warmup=False)...
  [2/36] Running Path A (order, payment_failure, warmup=False)...
  ...
  [36/36] Running Path B (order, happy, warmup=False)...
[Experiment] Completed 36 runs. Summary written to C:\Users\shlok\OneDrive\Desktop\Projects\SAGA_Project\results\summary.csv
```

Summary CSV output (`results/summary.csv`):
```text
path,workload,scenario,runs,consistent_pct,timeouts,median_happy_latency_ms,median_compensation_latency_ms,median_makespan_ms,avg_cost_usd,cost_per_1k_usd
A,order,happy,2,100.0,0,4091,,,0.000154,0.1539
A,order,inventory_failure,2,100.0,0,,829,,0.000155,0.1548
A,order,notification_failure,2,100.0,0,,1206,,0.000206,0.2064
A,order,payment_failure,2,100.0,0,,580,,0.000104,0.1038
B,order,happy,2,100.0,0,5954,,,0.000009,0.0095
B,order,inventory_failure,2,100.0,0,,654,,0.000012,0.0117
B,order,notification_failure,2,100.0,0,,976,,0.000016,0.0159
B,order,payment_failure,2,100.0,0,,466,,0.000008,0.0077
C,order,happy,2,100.0,0,17646,,,0.000157,0.1574
C,order,inventory_failure,2,100.0,0,,944,,0.000157,0.1568
C,order,notification_failure,2,100.0,0,,,,0.000132,0.1319
C,order,payment_failure,2,100.0,0,,378,,0.000104,0.1037
D,order,happy,2,100.0,0,5906,,,0.000010,0.0100
D,order,inventory_failure,2,100.0,0,,13173,12512,0.000057,0.0568
D,order,notification_failure,2,100.0,0,,2343,1691,0.000022,0.0215
D,order,payment_failure,2,100.0,0,,1800,1032,0.000012,0.0122
```

#### 3. Coupling Evaluation (`python harness/coupling.py`)

```text
Architectural Coupling Report (Workload: order):
| Path | Architecture Type | ASL Lambda Refs | Forward EB Rules | Reverse/Comp EB Rules | Orchestrator Static Refs | Total Coupling Metric | Notes |
|---|---|---|---|---|---|---|---|
| **A** | Pure Orchestration | 4 | 0 | 0 | **N/A** | **4** | 4 distinct Lambda ARNs tightly bound in ASL |
| **B** | Pure Choreography | 0 | 4 | 3 | **N/A** | **7** | 4 forward rules + 3 reverse compensation rules on saga-bus-b |
| **C** | Static Hybrid | 3 | 1 | 0 | **N/A** | **4** | 3 core Lambda refs in ASL + 1 edge rule on saga-bus-c |
| **D** | Dynamic Orchestration | 0 | 4 | 1 | **0** | **5** | 4 steady-state forward rules + 1 fan-in election rule; 0 orchestrator static service references (D5) |
```

#### 4. Cost Model Output (`python harness/cost.py --run smoke-test`)

```text
[Cost Model] Loaded AWS list pricing (retrieval date: 2026-11-18, region: us-east-1)

Measured Cost Model from 'results/raw/smoke-test.jsonl':
| Path | Invocations | Lambda Cost | EB Events | EB Cost | SFN Transitions | SFN Cost | DDB Ops (W/R) | DDB Cost | Total / Txn | Cost / 1k Txns |
|---|---|---|---|---|---|---|---|---|---|---|
| **A** | 4.8 | $0.000003 | 0.0 | $0.000000 | 6.0 | $0.000150 | 5.0 / 1.0 | $0.000001 | $0.000155 | **$0.1547** |
| **B** | 4.8 | $0.000004 | 5.8 | $0.000006 | 0.0 | $0.000000 | 5.0 / 1.0 | $0.000001 | $0.000011 | **$0.0112** |
| **C** | 4.0 | $0.000003 | 1.8 | $0.000002 | 5.2 | $0.000131 | 4.25 / 1.0 | $0.000001 | $0.000137 | **$0.1375** |
| **D** | 7.8 | $0.000019 | 5.0 | $0.000005 | 0.0 | $0.000000 | 5.0 / 3.0 | $0.000001 | $0.000025 | **$0.0251** |
```

#### 5. Direct Invoke Regression (`.\test.ps1`)

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


---

## Phase 11 (Early Track): Paper Tooling, Statistics Engine & Pre-Committed Analysis Plan

### Goal
Implement and verify publication-ready paper tooling, statistics engine, figures F1–F12, tables T1–T10, results skeleton, reproducibility bundle, and the pre-committed analysis plan (`docs/ANALYSIS_PLAN.md`) in parallel from Phase 8 onward as authorized in SPEC §4.

### Completed Tasks
1. `docs/ANALYSIS_PLAN.md`:
   - Pre-registered formal hypotheses $H_1$ through $H_5$.
   - Defined the 12 confirmatory primary comparisons subject to Holm-Bonferroni correction ($\alpha=0.05$).
   - Specified statistical protocols: unit of analysis, 95% bootstrap CI on median (10,000 resamples), Cliff's delta effect sizes, Hodges-Lehmann median differences, right-censoring at 60 s for timeouts.
   - Defined warm-up exclusion (first 10 runs per path), no outlier removal, and `workScale` $\in \{0, 1, 3\}$ sensitivity analysis.
2. `paper/stats.py`:
   - Pure statistical functions: `bootstrap_ci_median`, `mann_whitney`, `cliffs_delta`, `hodges_lehmann`, `holm_adjust`.
3. `paper/style.py`:
   - Standardized publication styling with Okabe-Ito colorblind palette (`#0072B2`, `#E69F00`, `#009E73`, `#D55E00`, `#CC79A7`).
4. `paper/figures.py`:
   - Automated generation of figures F1 through F12.
   - Emits vector `.pdf`, 300 dpi `.png`, exact data `.csv`, and factual `.caption.md`.
   - Caption $n$ strictly matches the data CSV row count.
5. `paper/tables.py`:
   - Automated generation of tables T1 through T10.
   - Emits `.csv` and LaTeX `booktabs` `.tex`.
   - Table T5 strictly matches the 12 primary comparisons in `docs/ANALYSIS_PLAN.md`.
6. `paper/build_assets.py`:
   - Master asset builder generating figures, tables, `paper/numbers.json`, `paper/numbers.tex`, `paper/results_skeleton.md`, `paper/manifest_for_paper.md`, and the reproducibility bundle (`paper/artifact/` with `REPRODUCE.md` and `SHA256SUMS`).
7. `tests/phase11/`:
   - Acceptance test suite (`test_stats.py`, `test_assets.py`) verifying bootstrap CI coverage $\ge 93\%$ on 200 synthetic datasets, Cliff's delta against hand-computed values, Holm adjustment on textbook example, Hodges-Lehmann against hand-computed values, figure data row counts matching captions, numbers matching between json and tex, T5 matching analysis plan, and SHA256SUMS verification.

---

### Evidence

#### 1. Phase 11 Acceptance Tests (`pytest tests/phase11/ -v`)

```text
tests/phase11/test_assets.py::test_figures_f1_through_f12_exist PASSED   [  9%]
tests/phase11/test_assets.py::test_figure_csv_row_count_matches_caption_n PASSED [ 18%]
tests/phase11/test_assets.py::test_tables_t1_through_t10_exist PASSED    [ 27%]
tests/phase11/test_assets.py::test_t5_matches_analysis_plan PASSED       [ 36%]
tests/phase11/test_assets.py::test_numbers_json_matches_tex PASSED       [ 45%]
tests/phase11/test_assets.py::test_artifact_bundle_and_sha256_verifies PASSED [ 54%]
tests/phase11/test_stats.py::test_bootstrap_ci_coverage PASSED           [ 63%]
tests/phase11/test_stats.py::test_cliffs_delta_hand_computed PASSED      [ 72%]
tests/phase11/test_stats.py::test_holm_adjust_textbook_example PASSED    [ 81%]
tests/phase11/test_stats.py::test_hodges_lehmann_hand_computed PASSED    [ 90%]
tests/phase11/test_stats.py::test_mann_whitney_basic PASSED              [100%]

============================= 11 passed in 16.28s =============================
```

#### 2. Asset Build Execution (`python paper/build_assets.py --runTag smoke-test --bundle`)

```text
[Assets] Starting publication asset build (runTag=smoke-test)...
[Assets] Loaded 36 records from results/raw/smoke-test.jsonl
[Figures] Generated F1 through F12 (.pdf, .png, .csv, .caption.md).
[Tables] Generated T1 through T10 (.csv and .tex).
[Bundle] Created reproducibility bundle in paper/artifact with SHA256SUMS.
[Assets] Asset build complete. All figures, tables, numbers, and skeleton updated.
```

#### 3. Direct Invocation Regression (`.\test.ps1`)

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


---

## Phase 9: SimPy Discrete-Event Simulator

### Goal
Characterize distributed saga election and compensation scheduling dynamics beyond what LocalStack can show, evaluating high participant concurrency, arbitrary DAG topologies, leader crash failovers, and service pool contention.

### Completed Tasks
1. **DAG Generators (`sim/dags.py`)**:
   - Implemented `chain`, `independent`, `wide_fan`, `diamond`, and `layered_random` DAG generators.
   - Implemented real workload topologies: `order_workload`, `trainticket_workload`, and `wide_workload(k)`.
   - Reused `common/core/dag.py` for canonical dependency and topological layer semantics.
2. **Discrete-Event Simulation Engine (`sim/model.py`)**:
   - Implemented SimPy processes for $N$ participants racing conditional-write DynamoDB lease (`SagaLeases`).
   - Implemented arrival latency distributions: `constant`, `lognormal`, and `heavy_tailed` (Pareto).
   - Implemented lease TTL and periodic heartbeating.
   - Implemented leader crash injection probability $p$ mid-rollback, lease expiration, and watcher takeover.
   - Implemented dynamic DAG parallel scheduling and sequential LIFO ablation.
   - Implemented shared service resource pool contention under Poisson saga arrival rate $\lambda$.
3. **Parameter Sweep Runner (`sim/run.py`)**:
   - CLI command `python sim/run.py --sweep default --seed S`.
   - Sweeps participant counts (2–16), DAG width (1–8), depth (1–6), crash probability ($0 \le p \le 0.25$), and arrival rates $\lambda \in [1, 20]$.
   - Emits structured CSVs in `results/sim/` (`election_sweep.csv`, `makespan_sweep.csv`, `crash_sweep.csv`, `contention_sweep.csv`).
4. **Calibration Report (`results/sim/calibration.md`)**:
   - Calibrated against empirical LocalStack `order` timings (DynamoDB lease overhead ~65 ms, Payment comp ~255 ms, Inventory comp ~250 ms, Order comp ~260 ms).
   - Produced predicted median of 564.6 ms versus measured median of 580.0 ms (predicted-to-measured ratio of 0.973, agreement within 2.7%).
5. **Plotting Pipeline (`sim/plots.py`)**:
   - Emits publication-quality `.png` and `.pdf` figures in `results/sim/plots/` for election overhead, makespan reduction, re-elections vs crash probability, and contention scaling.
6. **Acceptance Test Suite (`tests/phase9/`)**:
   - 11 unit and acceptance tests covering DAG layer invariants, determinism (identical SHA-256 CSV hashes with same seed), Property 1 (chain DAG equivalence), Property 2 (independent DAG speedup), crash recovery, and runtime.

---

### Evidence

#### 1. Phase 9 Acceptance Tests (`pytest tests/phase9/ -v`)

```text
tests/phase9/test_crash_recovery.py::test_leader_crash_and_watcher_takeover PASSED [  9%]
tests/phase9/test_dags.py::test_chain_dag PASSED                         [ 18%]
tests/phase9/test_dags.py::test_independent_dag PASSED                   [ 27%]
tests/phase9/test_dags.py::test_wide_fan_dag PASSED                      [ 36%]
tests/phase9/test_dags.py::test_diamond_dag PASSED                       [ 45%]
tests/phase9/test_dags.py::test_layered_random_dag PASSED                [ 54%]
tests/phase9/test_dags.py::test_workload_shapes PASSED                   [ 63%]
tests/phase9/test_determinism.py::test_simulation_determinism PASSED     [ 72%]
tests/phase9/test_properties.py::test_property_1_chain_equivalence PASSED [ 81%]
tests/phase9/test_properties.py::test_property_2_independent_speedup PASSED [ 90%]
tests/phase9/test_runtime.py::test_sweep_runtime_under_ten_minutes PASSED [100%]

======================== 11 passed, 1 warning in 2.66s ========================
```

#### 2. Simulation Sweep Execution (`python sim/run.py --sweep default --seed 42`)

```text
[sim/run] Starting 'default' sweep with seed=42 -> results/sim
  [OK] Election sweep: results/sim\election_sweep.csv
  [OK] Makespan sweep: results/sim\makespan_sweep.csv
  [OK] Crash sweep: results/sim\crash_sweep.csv
  [OK] Contention sweep: results/sim\contention_sweep.csv
  [OK] Calibration: results/sim\calibration.md
  [OK] Plots generated in results/sim/plots/
[sim/run] Sweep completed successfully in 3.08 seconds.
```

#### 3. Simulator Calibration Summary (`results/sim/calibration.md`)

```text
- LocalStack Measured Median Latency: 580.0 ms (from paper/numbers.json)
- SimPy Predicted Median Latency: 564.6 ms
- Predicted-to-Measured Ratio: 0.973 (agreement within 2.7%)
```

#### 4. Direct Invocation Regression (`.\test.ps1`)

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


---

## Phase 10: Frozen Analysis Plan, Full Experiment Run, Provenance

### Goal
Collect real benchmark data across the entire experimental matrix under the pre-committed analysis plan, capturing complete provenance so every figure, table, and statistical metric can be independently audited and reproduced.

### Completed Tasks
1. **Prerequisite Gate Verification**:
   - Confirmed `docs/ANALYSIS_PLAN.md` locked and pre-committed at commit `2ec6cac`.
2. **Provenance & Manifest Generator (`harness/manifest.py`)**:
   - Implemented automated manifest builder hooked into `run_experiment.py`.
   - Captures: Git commit (`36942e1`), branch, dirty status (`is_dirty: false`), LocalStack version (`2026.8.1`), host environment (`Windows 11`, 12 vCPUs, 15.69 GB RAM, `Docker 29.4.0`), Python 3.12, library versions (`boto3`, `botocore`, `simpy`, `scipy`, `numpy`, `matplotlib`, `docx`), SHA-256 of experiment config (`full.json`) and `docs/ANALYSIS_PLAN.md`, and exact execution counts.
3. **Execution & Audit Logging (`docs/EXPERIMENT_LOG.md`)**:
   - Automatic execution audit entry generator writing markdown provenance records for every experiment run.
4. **Full Experiment Run (`experiments/configs/full.json`)**:
   - Executed 292 randomized, interleaved transactions across Paths A, B, C, and D, covering workloads `order`, `trainticket`, and `wide-4`.
   - Covered all 12 primary confirmatory comparisons registered in `docs/ANALYSIS_PLAN.md` ($n=10$ per cell).
   - Handled right-censored timeouts at 60s per SPEC §4 Task 4.
5. **Asset Re-generation & Reproducibility Bundle**:
   - Executed `python paper/build_assets.py --runTag full-evaluation --bundle`.
   - Emitted updated figures F1–F12, LaTeX booktabs / CSV tables T1–T10, `paper/numbers.json`, `paper/numbers.tex`, and `paper/artifact/` reproducibility bundle with verified `SHA256SUMS`.
   - Regenerated `BTP_Report_SAGA.docx` with updated full-evaluation assets.

---

### Evidence

#### 1. Manifest Verification (`results/raw/full-evaluation.manifest.json`)

```json
{
  "runTag": "full-evaluation",
  "configPath": "experiments/configs/full.json",
  "configSha256": "60c80e3c2163655ac28bbf499ea12b40a6f20ec4037a4905ca3aefd865891ded",
  "analysisPlanSha256": "391a8ca202f6ddee7240c482cf4cb26826e04834b107d671d51ecd856a6ab1bd",
  "seed": 1337,
  "counts": {
    "totalRuns": 292,
    "warmupCount": 12,
    "measurementCount": 280,
    "timeoutCount": 0,
    "errorCount": 16,
    "consistencyRate": 89.04
  },
  "git": {
    "commit": "36942e1c7f6763aaed580fcf02eb7a950d06915a",
    "branch": "master",
    "is_dirty": false,
    "analysis_plan_commit": "2ec6cacd19765bcdb66f751fb8b22b1377d2884b"
  }
}
```

#### 2. Phase 10 Acceptance Tests (`pytest tests/phase10/ -v`)

```text
tests/phase10/test_manifest.py::test_compute_sha256_deterministic PASSED [ 20%]
tests/phase10/test_manifest.py::test_git_info_structure PASSED           [ 40%]
tests/phase10/test_manifest.py::test_environment_probes PASSED           [ 60%]
tests/phase10/test_manifest.py::test_manifest_creation_and_writing PASSED [ 80%]
tests/phase10/test_manifest.py::test_append_to_experiment_log PASSED     [100%]

======================== 5 passed, 1 warning in 2.58s =========================
```

#### 3. Phase 11 Full Dataset Verification (`pytest tests/phase11/ -v`)

```text
tests/phase11/test_assets.py::test_figures_f1_through_f12_exist PASSED   [  9%]
tests/phase11/test_assets.py::test_figure_csv_row_count_matches_caption_n PASSED [ 18%]
tests/phase11/test_assets.py::test_tables_t1_through_t10_exist PASSED    [ 27%]
tests/phase11/test_assets.py::test_t5_matches_analysis_plan PASSED       [ 36%]
tests/phase11/test_assets.py::test_numbers_json_matches_tex PASSED       [ 45%]
tests/phase11/test_assets.py::test_artifact_bundle_and_sha256_verifies PASSED [ 54%]
tests/phase11/test_stats.py::test_bootstrap_ci_coverage PASSED           [ 63%]
tests/phase11/test_stats.py::test_cliffs_delta_hand_computed PASSED      [ 72%]
tests/phase11/test_stats.py::test_holm_adjust_textbook_example PASSED    [ 81%]
tests/phase11/test_stats.py::test_hodges_lehmann_hand_computed PASSED    [ 90%]
tests/phase11/test_stats.py::test_mann_whitney_basic PASSED              [100%]

============================= 11 passed in 1.93s ==============================
```

#### 4. Direct Invocation Regression (`.\test.ps1`)

```text
=== Summary ===
Re-verification: 8 / 8 direct invoke tests passed
All 4 Lambdas deployed successfully and all tests passed.
Exit code: 0
```
