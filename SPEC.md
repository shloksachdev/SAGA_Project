# SPEC.md: Saga Pattern Comparison, Implementation Spec

Audience: an implementation agent. All design reasoning is already done; your job is to build exactly what is written, one phase at a time, and report evidence.

Source documents: `Group_Project_Proposal_Saga_Pattern_v2.docx` (the proposal) and the repo `shloksachdev/SAGA_Project` (README, file list). The spec author could NOT read the repo's code files (handlers, `setup.ps1`, `deploy-lambda.ps1`, `test.ps1`). Phase 0 therefore starts with an audit, and where the audit contradicts this spec, you stop and report instead of guessing.

---

## 0. Rules for the implementing agent

1. Work on **one phase at a time**. Finish its Acceptance block, paste the evidence (command output) into `docs/PHASE_LOG.md`, then stop and wait for a human "go" before the next phase.
2. Never break existing behavior: `.\test.ps1` must pass at the end of every phase. Existing handler inputs (`action`, `simulateFailure`) must keep working; new fields are optional and additive.
3. New tooling is **Python 3.11+ with boto3** (endpoint `http://localhost:4566`, region and dummy credentials copied from the existing scripts). Do not write new tooling in PowerShell. Existing `.ps1` files stay as they are, except where a phase says to extend them.
4. Environment gotchas inherited from the README, which all still apply:
   - LocalStack free tier loses IAM, EventBridge and Step Functions state on restart, so rerun setup after every restart. New provisioning must be **idempotent** (safe to rerun).
   - `aws lambda invoke` returns exit code 0 even when the function crashed, so always check `FunctionError` (boto3: `response.get("FunctionError")`).
   - Never pass inline JSON through PowerShell. Write files with `-Encoding ascii`, or use boto3.
   - Use `aws --endpoint-url=http://localhost:4566`, not `awslocal`.
5. If a LocalStack feature does not behave as a phase assumes, do not improvise a large workaround. Record it in `docs/localstack_findings.md`, use the fallback named in the phase if one exists, and otherwise write `docs/BLOCKERS.md` and stop.
6. No secrets in git. Never commit `.env`. Keep commits small, one logical change each, message prefix `phaseN:`.
7. Every file you create gets a short header comment stating its purpose and which phase created it.
8. Do not add features not in this spec. If you think something is missing, write it in `docs/PROPOSALS.md` and move on.

---

## 1. The project in one paragraph

Four coordination strategies for the same four-step order saga (Order → Payment → Inventory → Notification) are built on LocalStack and compared:

- **A**: pure orchestration (Step Functions)
- **B**: pure choreography (EventBridge)
- **C**: static hybrid (Step Functions core plus an EventBridge edge)
- **D**: the contribution. It is choreographed (same as B) while things go well. When a step fails, the participating services race for a DynamoDB conditional-write lease. The winner becomes a temporary orchestrator for that one saga instance. It builds a compensation dependency graph from data in the step records and dispatches independent compensations in parallel. The lease then expires and the system is choreography again.

Primary objective: minimize **compensation makespan** (failure detected → full rollback complete), subject to a **coupling ceiling** (the elected role holds no standing references). Cost is the tie-breaker. Results are reported per metric and as a latency-vs-coupling Pareto comparison, never collapsed to a single score.

---

## 2. Design decisions already made (do not re-litigate; flag if you believe one is wrong)

| # | Decision | Reasoning |
|---|---|---|
| D1 | **One set of four service Lambdas shared by all paths.** Behavior is parameterized by `path` in the saga envelope. | Coordination must be the only variable between paths. Separate per-path service code would add confounds. |
| D2 | **Pure/adapter split.** `common/core/` contains pure Python with no boto3 (DAG building, scheduling logic). AWS code lives in other `common/` modules. | Pure logic is unit-testable without LocalStack and is reused verbatim by the SimPy simulator, so the simulator cannot drift from the real algorithm. |
| D3 | **Single measurement source.** Every component writes append-only rows to a `SagaTrace` table with identical event names across paths. All metrics are derived offline from it. | "Instrument all four paths identically" is only credible if one mechanism measures all of them. |
| D4 | **Simulated work time** per step (`workMs`, with jitter), identical across paths, scaled by `workScale` ∈ {0, 1, 3}. | LocalStack's emulation overhead is large and noisy. With near-zero step time, any makespan difference would be buried in noise. `workScale=0` is run once as a pure-overhead sensitivity check. |
| D5 | **Compensation dependencies are self-declared in each step's record at completion time** (`compensateAfter`, `compensatorFn`, `compensateAction`). The elected orchestrator builds its DAG only from those records. | If the orchestrator imported a central workflow definition or hard-coded function names, it would be a fixed orchestrator in disguise and the "no standing references" claim would be false. Enforced by a test (Phase 5). |
| D6 | **Lease = conditional `UpdateItem` with an explicit `leaseExpiresAt` timestamp.** Do NOT use DynamoDB TTL for expiry. `epoch` increments on every acquisition and is the fencing token. | DynamoDB TTL deletion is lazy (can lag by a long time) and would make expiry untestable. An explicit timestamp is deterministic. |
| D7 | **No standing process for re-election.** Participants that lose an election stay alive as *watchers*, sleep until the lease expiry, and re-attempt if the saga is not terminal. | Lambda has no daemon. A watcher loop keeps "no always-on controller" true. Its cost (billed waiting time) is counted in the cost metric and listed in the threats to validity. |
| D8 | **All step actions are idempotent** via a status state machine in `SagaSteps` (conditional transitions). | EventBridge, Lambda async retries and re-election all produce duplicate deliveries. Duplicates must be harmless, and verifiably so. |
| D9 | **Baselines are the textbook versions.** A compensates as a sequential reverse chain. B compensates as a reverse event chain (each service reacts to its downstream neighbour's failure or compensated event). Stretch variants A-parallel (Step Functions `Parallel` state) and B-fanout are Phase 10 optional extras. | Reviewers will ask whether A or B could simply parallelize too. We state plainly that the default baselines do not, and measure the stretch variants if time allows. |
| D10 | **One EventBridge bus per path**: `saga-bus-b`, `saga-bus-c`, `saga-bus-d`. | Rule counts per bus are then a clean coupling measurement, and paths cannot cross-trigger. |
| D11 | **Failed step is not compensated** unless its record sets `compensateOnFailure: true` (default false). | The failing step is treated as atomic. Idempotent compensation of it would be harmless but would distort makespan. |
| D12 | **Identical retry policy for compensation in all paths:** 3 attempts, fixed 1000 ms interval, no backoff growth. Constants live in `common/policy.py`. | Step Functions `IntervalSeconds` has a 1 s minimum and integer granularity, so 1000 ms is the common denominator. Same policy everywhere keeps the comparison fair. |
| D13 | **Business failures in event-driven paths (B, C-edge, D) return normally** after writing `STEP_FAILED` and publishing the failure event. In Step Functions paths (A, C-core) they raise an exception whose class name is the error name. | An unhandled error in an async Lambda invocation triggers Lambda's automatic retries, which would create duplicate events and corrupt measurements. |
| D14 | **Cost is computed analytically** from counted units multiplied by a price table. LocalStack does not bill. | Counted units: Lambda invocations and billed GB-seconds, EventBridge events, Step Functions state transitions, DynamoDB read and write units. |
| D15 | **Timestamps are milliseconds from `time.time_ns() // 1_000_000`, taken inside the component that observes the event.** Everything runs on one Docker host, so clocks agree. | Single-host assumption is recorded in the threats to validity. |

### Compensation dependency model (the heart of the contribution)

Each step declares `compensateAfter`: a list of step names whose compensation must finish before this step's compensation may start. The special value `["*"]` means "after every other step that needs compensating".

Default `order` workload declarations:

| Step | compensateAfter | Compensator action |
|---|---|---|
| Order | `["*"]` | `cancel` |
| Payment | `[]` | `compensate` |
| Inventory | `[]` | `release` |
| Notification | `[]` | `unnotify` |

What this implies, and the spec states it up front so nobody mistakes it for a bug:

| Failure injected at | Completed steps | LIFO (sequential) | Dependency-aware parallel |
|---|---|---|---|
| Payment | Order | 1 step | 1 step. **No gain.** |
| Inventory | Order, Payment | 2 sequential | 2 sequential (Order last). **No gain.** |
| Notification | Order, Payment, Inventory | 3 sequential | Payment ∥ Inventory, then Order = 2 steps. **Gain.** |

On a 4-step linear saga with "cancel Order last", the scheduler can only help when failure happens at the last step. The proposal injects payment declines and inventory shortages, which are exactly the cases with no gain. Therefore:

- The harness MUST sweep failure **depth** (Payment, Inventory, Notification), not just failure type.
- A "no gain at early depths" result is a valid finding, not a defect.
- Phase 7B adds a synthetic wide-fan workload so the claim can be tested where parallelism exists. The SimPy simulator (Phase 9) covers shapes beyond that.

---

## 3. Shared contracts (materialize in Phase 0 as `docs/CONTRACTS.md`, `contracts/*.json`, `common/contracts.py`)

### 3.1 Saga envelope (input to any path, carried through every event and state)

```json
{
  "sagaId": "uuid4",
  "path": "A | B | C | D",
  "workload": "order | trainticket | wide-2 | wide-4 | wide-6",
  "runTag": "string identifying the experiment run",
  "startedAt": 1700000000000,
  "payload": { "customerId": "c1", "items": [{"sku": "S1", "qty": 1}], "amount": 49.0 },
  "workScale": 1.0,
  "faults": {
    "Inventory": { "forward": "fail", "errorName": "InventoryShortage" },
    "Payment":   { "compFailFirstN": 1 }
  },
  "leaderFault": "crash_after:1",
  "compMode": "parallel | lifo"
}
```

- `faults.<Step>.forward = "fail"` makes the forward action fail with `errorName` (`PaymentDeclined`, `InventoryShortage`, or generic `StepFailure`).
- `faults.<Step>.compFailFirstN = N` makes the first N compensation attempts of that step fail transiently.
- `leaderFault` (path D only): `crash_after:K` means the elected leader returns without releasing the lease or heartbeating after dispatching K compensations.
- `compMode` is meaningful for path D only; default `parallel`.
- The existing boolean `simulateFailure` stays supported as an alias for `faults.<this step>.forward = "fail"`.

### 3.2 DynamoDB tables (all created idempotently by `infra/provision.py`; reuse existing order table and `SagaLeases` if the audit finds them)

| Table | Key | Attributes |
|---|---|---|
| `SagaRuns` | `sagaId` (S) | `path, workload, runTag, status (RUNNING/COMPLETED/COMPENSATING/COMPENSATED/COMPENSATION_FAILED), startedAt, failedAt, failedStep, compensatedAt, stepCounter (N)` |
| `SagaSteps` | `sagaId` (S), `step` (S) | `status (COMPLETED/FAILED/COMPENSATING/COMPENSATED/COMP_FAILED), seq (N, completion order), completedAt, compensatorFn, compensateAction, compensateAfter (L), compensateOnFailure (BOOL), compInvocations (N), compApplied (N), compensatedAt` |
| `SagaLeases` | `sagaId` (S) | `ownerId, epoch (N), leaseExpiresAt (N), status (ACTIVE/DONE), electedAt` |
| `SagaTrace` | `sagaId` (S), `sk` (S = zero-padded ms + `#` + random suffix) | `event, step, actor, path, detail (M)` |

`seq` is assigned by an atomic `ADD stepCounter 1` on the `SagaRuns` item with `ReturnValues=UPDATED_NEW`. It defines "completion order" for LIFO.

### 3.3 Trace event names (exact strings; the metrics code depends on them)

`SAGA_STARTED, STEP_STARTED, STEP_COMPLETED, STEP_FAILED, SAGA_COMPLETED, COMP_NEEDED_PUBLISHED, ELECTION_START, LEASE_ACQUIRED, LEASE_LOST, LEASE_RENEWED, LEASE_TAKEOVER, WATCHER_RETRY, COMP_DISPATCHED, COMP_STARTED, COMP_COMPLETED, COMP_FAILED_ATTEMPT, COMP_DUPLICATE_IGNORED, SAGA_COMPENSATED, SAGA_COMPENSATION_FAILED, NOTIFICATION_DLQ, LAMBDA_INVOKE, LAMBDA_END, DDB_OPS, EVENTS_PUT, SFN_TRANSITIONS`

Rule for who writes `SAGA_COMPENSATED`: the component executing the final compensating action. In A, B and C this is the Order `cancel` handler. In D it is the leader, once the DAG drains.

### 3.4 Events (paths B, C-edge, D)

- Bus `saga-bus-{b|c|d}`. `source` = `saga.<service>` (lowercase). `detail` = the saga envelope plus `{step, result, ts}`.
- `detail-type` values: `SagaStarted, OrderCreated, PaymentCharged, PaymentFailed, InventoryReserved, InventoryFailed, NotificationSent, NotificationFailed, CompensationNeeded` (D only), and for path B compensation: `InventoryCompensated, PaymentCompensated, OrderCancelled`.
- Rule targets use input path `$.detail` so the handler receives the envelope directly. Add Lambda invoke permission for each rule.
- All new handler code must accept either a direct-invoke payload or an EventBridge-wrapped event (`common/events.py: parse_event()`).

### 3.5 Metric definitions (exact)

| Metric | Definition |
|---|---|
| compensation_latency | `SAGA_COMPENSATED.ts − STEP_FAILED.ts` |
| election_time (D) | `LEASE_ACQUIRED.ts − COMP_NEEDED_PUBLISHED.ts` (first acquisition) |
| scheduling_makespan (D) | `SAGA_COMPENSATED.ts − LEASE_ACQUIRED.ts` |
| happy_latency | `SAGA_COMPLETED.ts − SAGA_STARTED.ts` |
| throughput | completed sagas ÷ (last completion − first start) during the fixed load profile |
| coupling | scripted count, defined in Phase 8 |
| cost per 1,000 txns | sum over counted units × price table, divided by txns × 1000, for a mixed run at 10% failure rate |
| recovery_consistency | % of failed runs whose final state satisfies the invariant in Phase 8 within 60 s |

---

## 4. Phases

Dependency order: P0 → P1 → {P2, P3, P4, P8, P9a} in parallel → P5 (needs P4) → P6 (needs P2 + P3) → P7A/P7B (need P1 + builders from P2/P3) → P10 (needs everything, plus an approved `ANALYSIS_PLAN.md`) → P11. P11's statistics module and figure/table code can be built and tested on synthetic data in parallel from P8 onward.

### Phase 0: Audit, LocalStack spikes, contracts, repo hygiene

**Goal:** replace assumptions with facts and freeze the contracts.
**Why first:** this spec was written without seeing the code. Every later phase depends on correct names and behaviors.

Tasks:
1. Read every file in the repo. Write `docs/REPO_AUDIT.md` covering: names of the existing bus, tables, IAM role, state machine; each handler's exact input and output shape; how handlers reach DynamoDB (endpoint/credentials pattern); how `deploy-lambda.ps1` packages code; region and credentials; Lambda timeouts and memory. End with a section **"Divergences from SPEC.md"**.
2. Hygiene:
   - `git mv gitattributes .gitattributes`.
   - README says `bash setup.sh` but the file is not in the repo. Create `setup.sh` mirroring `setup.ps1` (or, if you cannot test bash, mark it clearly untested in the README).
   - Add to `.gitignore`: `results/raw/`, `__pycache__/`, `.pytest_cache/`, `build/`, `*.zip`.
3. LocalStack spikes: create `spikes/spike_S1.py … spike_S8.py` and `spikes/run_all.py` (prints PASS/FAIL table). Record outcomes and chosen fallbacks in `docs/localstack_findings.md`.

| Spike | Verifies | Fallback if FAIL |
|---|---|---|
| S1 | EventBridge rule → Lambda delivers `$.detail` as the Lambda event | Use full event and unwrap in `parse_event()` |
| S2 | Step Functions → Lambda with named-error `Catch` and `Retry` (IntervalSeconds 1) | Catch `States.ALL` only |
| S3 | Step Functions `putEvents` service integration | A tiny Lambda Task that publishes the event |
| S4 | DynamoDB `UpdateItem` with `SET epoch = if_not_exists(epoch,:z) + :one` and a condition `attribute_not_exists(sagaId) OR leaseExpiresAt < :now` returns `ConditionalCheckFailedException` on loss | Use `GetItem` + conditional `PutItem` with a version attribute |
| S5 | `TransactWriteItems` with a `ConditionCheck` | Skip fencing transactions; rely on D8 idempotency only (record this) |
| S6 | A Lambda invoking another Lambda synchronously from inside the container, 4 concurrent invokes via a thread pool | Dispatch via `CompensateStep` events and have the leader poll `SagaSteps` |
| S7 | EventBridge target `RetryPolicy` + `DeadLetterConfig` (SQS) | Implement retry-then-DLQ inside the Notification handler |
| S8 | `sfn.get_execution_history` returns state-entered events | Count transitions from the known ASL path |

4. Materialize contracts: `docs/CONTRACTS.md` (copy of §3), `contracts/envelope.schema.json`, `common/contracts.py` (dataclasses or TypedDicts + the trace event-name constants).

Acceptance:
- `python spikes/run_all.py` prints a PASS/FAIL table; `docs/localstack_findings.md` exists.
- `.\test.ps1` passes.
- `git status` shows only intended files.

---

### Phase 1: Shared foundation

**Goal:** one common library so all paths run the same step logic and emit identical measurements.

Layout (new): `common/` (`aws.py, events.py, trace.py, steps.py, work.py, metered.py, policy.py, workloads.py, contracts.py`), `common/core/` (pure, empty for now), `infra/provision.py`, `tests/phase1/`.

Tasks:
1. `common/aws.py`: boto3 client factory using the same endpoint/credential pattern the existing handlers use (from the audit).
2. `common/policy.py`: `COMP_MAX_ATTEMPTS=3`, `COMP_INTERVAL_MS=1000`, `LEASE_TTL_MS=5000`, `HEARTBEAT_MS=LEASE_TTL_MS//3`, `WATCH_MAX_ROUNDS=4`, `WATCH_JITTER_MS=300`.
3. `common/workloads.py`: workload configs. Each step: `name, forwardFn, forwardAction, compensatorFn, compensateAction, compensateAfter, compensateOnFailure, forwardMs, compensateMs, jitterMs`. Implement `order` now (defaults 150/150 ms, jitter 30; use the declaration table in §2). `Payment` and `Inventory` forward may raise their named errors.
4. `common/work.py`: `do_work(ms, jitter, scale)` sleeping `ms*scale ± jitter` (never negative); `apply_faults(envelope, step, phase, attempt)`.
5. `common/steps.py`: idempotent step state machine over `SagaSteps`:
   - `begin_forward` (conditional put, status STARTED/COMPLETED; duplicate delivery returns `ALREADY_DONE`).
   - `complete_forward` (assigns `seq` via the atomic counter; writes `compensatorFn`, `compensateAction`, `compensateAfter`, `compensateOnFailure` from workload config into the record).
   - `fail_forward`.
   - `begin_compensation`: conditional transition COMPLETED→COMPENSATING; increments `compInvocations`; if already COMPENSATED returns `NOOP` and writes `COMP_DUPLICATE_IGNORED`.
   - `complete_compensation`: COMPENSATING→COMPENSATED, increments `compApplied` exactly once (conditional).
6. `common/trace.py`: `emit(sagaId, event, step=None, actor=None, **detail)`; never raises (trace failure must not break a saga; log it instead).
7. `common/metered.py`: wrapper that counts boto3 calls by service and operation (excluding `SagaTrace` writes) and flushes one `DDB_OPS` / `EVENTS_PUT` / `LAMBDA_END` summary per invocation.
8. Refactor the 4 handlers to use the above. Preserve `action` names and the `simulateFailure` alias. Event emission is controlled by path (see §3.4 and D13): paths B, D and C-edge publish events; A and C-core do not.
9. `infra/provision.py`: idempotently create `SagaRuns, SagaSteps, SagaTrace`, verify `SagaLeases`, create buses `saga-bus-b/c/d`. Call it from the end of both `setup.ps1` and `setup.sh`.
10. Extend `deploy-lambda.ps1` so the zip includes the `common/` package alongside the handler.

Acceptance:
- `.\setup.ps1` runs twice with no errors; `.\test.ps1` passes.
- `pytest tests/phase1 -q` passes. It must include: (a) forward invoked twice for the same `sagaId` applies once; (b) compensation of a non-COMPLETED step returns `NOOP`; (c) compensation twice yields `compApplied == 1`, `compInvocations == 2`; (d) `workScale=0` runs without sleeping; (e) `faults` makes the named step fail with the named error.
- Direct invoke of each handler with an envelope produces correct `SagaSteps` and `SagaTrace` rows.

---

### Phase 2: Path A (pure orchestration)

**Goal:** a Step Functions state machine that runs the saga and compensates as a sequential reverse chain.

Tasks:
1. `paths/a/build_asl.py`: generate ASL from the workload config (not hand-written JSON). Forward: Order → Payment → Inventory → Notification → `Succeed`. Each forward Task has `Catch` on `States.ALL` routing to the compensation chain for the steps completed *before* it. Compensation tasks use `Retry` (`MaxAttempts` 3, `IntervalSeconds` 1, `BackoffRate` 1.0) from `common/policy.py`. Chain ends in a Fail/terminal state "Compensated".
2. `paths/a/deploy.py` (idempotent create-or-update) and `paths/a/run.py` (`start_saga(envelope) -> sagaId`, waits for terminal state).
3. Handlers raise named exceptions in this path (D13). `SAGA_STARTED` is written by `run.py`; `SAGA_COMPLETED` by the Notification handler.
4. Add `paths/a/deploy.py` to the provisioning flow (called from `infra/provision.py` or its own documented command).

Acceptance (`pytest tests/phase2 -q`):
- Happy run: `SagaRuns.status == COMPLETED`, 4 steps COMPLETED.
- Failure at each of Payment, Inventory, Notification: final `COMPENSATED`; exactly the previously-completed steps are COMPENSATED, in reverse order by `seq`; the failed step is not compensated; trace has `STEP_FAILED` then `SAGA_COMPENSATED`.
- `compFailFirstN=1` on one step: run still ends COMPENSATED (retry worked) and trace shows one `COMP_FAILED_ATTEMPT`.
- Duplicate-safe: re-running a compensation task directly leaves `compApplied == 1`.

---

### Phase 3: Path B (pure choreography)

**Goal:** EventBridge-only saga with a reverse event chain for compensation.

Tasks:
1. `paths/b/provision.py`: for bus `saga-bus-b`, create rules generated from the workload config:
   - Forward: service *i* subscribes to the success event of service *i−1* (Order subscribes to `SagaStarted`).
   - Compensation (D9 reverse chain): service *i* subscribes to `{Step(i+1)Failed, Step(i+1)Compensated}` (the Order cancel rule is the end of the chain). Each rule targets one Lambda with input path `$.detail`, and each Lambda gets invoke permission.
2. Handlers in path B: perform the action, write step state, publish the result event, return normally even on business failure (D13). The last forward step writes `SAGA_COMPLETED`. Order cancel writes `SAGA_COMPENSATED`.
3. `paths/b/run.py`: publish `SagaStarted` with the envelope; poll `SagaRuns` until terminal or timeout (60 s).
4. Compensation retry for B is done inside the handler (loop with `COMP_INTERVAL_MS`, `COMP_MAX_ATTEMPTS`), not by event redelivery.

Acceptance (`pytest tests/phase3 -q`): same scenarios as Phase 2, plus no duplicate side effects when the same event is published twice (`compApplied == 1`), and `python -m harness.coupling --path b` is not yet required.

---

### Phase 4: Path D part 1, lease election

**Goal:** a correct, tested, fault-tolerant leader election with no standing process. The compensation runner is pluggable here and real in Phase 5.

Tasks:
1. `common/lease.py`:
   - `try_acquire(saga_id, owner_id, ttl_ms)`: single conditional `UpdateItem`, condition `attribute_not_exists(sagaId) OR (leaseExpiresAt < :now AND #status <> :done)`, sets `ownerId, leaseExpiresAt, status=ACTIVE, epoch = if_not_exists(epoch,:zero)+:one, electedAt`. Returns `Lease(epoch, owner, expires)` or `None` on `ConditionalCheckFailedException`.
   - `renew(lease)`: conditional on `ownerId` and `epoch` matching.
   - `release_done(lease)`: sets `status=DONE` under the same condition.
   - Emits `LEASE_ACQUIRED / LEASE_LOST / LEASE_RENEWED / LEASE_TAKEOVER` (takeover = acquisition with epoch > 1).
2. `common/election.py`:
   - `participate(envelope, my_step)`: a service is a *participant* only if it has a step record for this saga with status COMPLETED, or it is the failed step. Non-participants return immediately.
   - A participant calls `try_acquire`. Winner returns a leader context with a background heartbeat thread (renew every `HEARTBEAT_MS`; stops on a flag).
   - Losers run `watch()` (D7): up to `WATCH_MAX_ROUNDS`; sleep until the observed `leaseExpiresAt` + random jitter (≤ `WATCH_JITTER_MS`); if `SagaRuns.status` is terminal, exit; else attempt acquisition and, on a win, become the leader and *resume*.
   - If rounds are exhausted: write `SAGA_COMPENSATION_FAILED` and set the run status `COMPENSATION_FAILED`.
   - Leader entry point takes a `compensation_runner(leader_ctx, envelope)` callable.
3. Path D forward flow: reuse Path B's forward rules, on `saga-bus-d`. On a forward failure the failing service writes `STEP_FAILED`, publishes `<X>Failed` and `CompensationNeeded` (writing `COMP_NEEDED_PUBLISHED`). Create one rule matching `CompensationNeeded` that targets **all four** services with `action=elect`.
4. `leaderFault=crash_after:K` support: the leader stops heartbeating and returns without releasing the lease after the runner reports K dispatches.
5. Lambda timeout for the four service functions must be ≥ 60 s in this path (set in `deploy-lambda.ps1` or provisioning; record in the audit file).

Acceptance (`pytest tests/phase4 -q`, with a trivial runner that records its call):
- Race: 10 threads call `try_acquire` for one saga → exactly 1 winner.
- Expiry takeover: after TTL passes, a second owner acquires and `epoch` increments; the old owner's `renew` then fails.
- A lease with `status=DONE` cannot be reacquired.
- End-to-end: forced failure produces exactly one `LEASE_ACQUIRED` among participants; non-participants do nothing; others log `LEASE_LOST` and finish as watchers once the run is terminal.
- Leader-crash: with the trivial runner crashing, a watcher takes over (`LEASE_TAKEOVER`, epoch 2) within `LEASE_TTL_MS + WATCH_JITTER_MS + 2000 ms`.

---

### Phase 5: Path D part 2, dependency graph scheduler plus LIFO ablation

**Goal:** the elected leader computes and runs the compensation plan. LIFO is the controlled ablation.

Tasks (pure first, then adapter):
1. `common/core/dag.py` (no boto3): `build_compensation_graph(step_records, failed_step) -> Graph`.
   - Nodes: steps with status COMPLETED or COMPENSATING, plus the failed step only if its `compensateOnFailure` is true.
   - Edges from each node's `compensateAfter` (resolve `"*"` to every other node). A dependency on a step already COMPENSATED or not in the node set is treated as satisfied.
   - Raise `CyclicDependency` on cycles.
   - Provide `layers()` and `ready(done_set)`.
2. `common/core/scheduler.py` (no boto3; the executor function is injected):
   - `run_parallel(graph, exec_fn, max_workers=8)`: dispatch every ready node, release dependents as nodes complete.
   - `run_lifo(graph, exec_fn)`: execute nodes sequentially in descending `seq` order (this ignores `compensateAfter`, which is the point of the ablation; Order-last still holds because it has the lowest `seq`).
   - Failure policy: retry per `common/policy.py`; after exhaustion mark the node FAILED, do not dispatch its dependents, finish independent branches, and return `COMPENSATION_FAILED`.
3. `common/orchestrator.py` (adapter): `exec_fn(node)` calls `lambda.invoke` synchronously on `node.compensatorFn` with `{"action": node.compensateAction, "saga": envelope, "step": node.step}` (both read from the step record). Writes `COMP_DISPATCHED / COMP_STARTED / COMP_COMPLETED`. After the DAG drains, writes `SAGA_COMPENSATED`, sets run status COMPENSATED, and calls `release_done`. On resume (after takeover), nodes already COMPENSATED are skipped; nodes stuck in COMPENSATING are re-dispatched (idempotent per D8).
4. Wire the runner into Phase 4's election. Honor `envelope.compMode`.
5. **Enforcement test of D5:** `tests/phase5/test_no_static_refs.py` statically checks (AST or grep) that `common/election.py`, `common/lease.py`, `common/orchestrator.py` and `common/core/*` do not import or reference `workloads` or any hard-coded function names (`Order`, `Payment`, `Inventory`, `Notification`, `order_handler`, …).

Acceptance (`pytest tests/phase5 -q`):
- Unit tests on `dag.py`/`scheduler.py` with a fake executor and virtual time: chain, diamond, star with `"*"`, all-independent, wide fan, cycle detection, transient failure with retry, permanent failure that blocks dependents but not siblings, resume with some steps already COMPENSATED. Makespan for all-independent equals the max node duration; for a chain it equals the sum.
- Integration, failure injected at Notification: run ends COMPENSATED; trace shows Payment and Inventory compensation intervals **overlapping**; Order's `COMP_STARTED` is after both complete.
- Same scenario with `compMode=lifo`: intervals do **not** overlap.
- Duplicate `CompensationNeeded` published twice: single compensation effect (`compApplied == 1` for every step).
- Leader crash after 1 dispatch (`leaderFault`): takeover completes the saga, `compApplied == 1` for all steps, one `LEASE_TAKEOVER`.
- `test_no_static_refs` passes.

---

### Phase 6: Path C (static hybrid)

**Goal:** the fixed-split baseline, reusing A and B parts.

Tasks:
1. State machine (`paths/c/build_asl.py`): core = Order → Payment → Inventory (Catch → sequential compensation chain exactly as in Path A for those three steps), then publish `OrderCoreCompleted` to `saga-bus-c` (Step Functions `putEvents` integration if S3 passed, otherwise a publisher Lambda task).
2. Edge: Notification subscribes to `OrderCoreCompleted` via a rule on `saga-bus-c`. Target retry policy: 2 attempts; dead-letter queue (SQS) for exhaustion. Notification failure writes `NOTIFICATION_DLQ` and does NOT roll back the core (matches the proposal: "edge retry-via-DLQ"). `SAGA_COMPLETED` is written by Notification on success.
3. Assumption flagged: Order creation is part of the orchestrated core (the proposal names only Payment and Inventory explicitly).

Acceptance (`pytest tests/phase6 -q`):
- Happy path completes via the edge.
- Failure at Payment and at Inventory: core compensated in reverse order, `SAGA_COMPENSATED` present, Notification never ran.
- Notification forced to fail: `NOTIFICATION_DLQ` event, DLQ has the message, core steps remain COMPLETED, run status reflects "completed with edge failure" (use `COMPLETED` with trace flag `edgeFailure=true`).

---

### Phase 7A: TrainTicket-derived workload

**Goal:** a second workload with a different shape and timing, on the same four services.

Tasks:
1. Add workload `trainticket` to `common/workloads.py` with the mapping Order=book, Payment=pay, Inventory=seat-allocate, Notification=confirmation. Per-step timings differ from `order` (pay/refund ≈ 300 ms, seat release ≈ 200 ms, others 100 ms). `compensateAfter`: Order `["*"]`, Payment `["Inventory"]` (refund only after the seat is released), Inventory `[]`, Notification `[]`.
2. Confirm builders for A/B/C/D generate correct artifacts from this config with no per-workload code.
3. Document honestly in `docs/WORKLOADS.md` that this is a **shape-level port** (book → pay → seat-allocate → cancel/refund semantics and timings), not an execution of the real TrainTicket services, so the report must call it "TrainTicket-derived".

Acceptance: Phase 2/3/5/6 test scenarios parameterized to also pass with `workload=trainticket` on all four paths (`pytest tests -k trainticket -q`).

### Phase 7B: Synthetic wide-fan workload (recommended; higher cut-priority than 7A)

**Goal:** a workload where compensation parallelism actually exists, so the central claim is testable on real LocalStack runs.

Tasks:
1. `generic_handler.py`: one handler parameterized by env `STEP_NAME` (uses the same `common/steps.py` logic). Deploy `Step1 … Step6` copies via `deploy-lambda.ps1`-equivalent Python.
2. Workloads `wide-2`, `wide-4`, `wide-6`: Order first, then *k* sequential forward steps, all with `compensateAfter=[]` except Order `["*"]`. Compensation durations differ per step (e.g. 100–400 ms) so makespan(LIFO) = sum vs makespan(parallel) = max + Order.
3. Builders from P2/P3/P6/P4 must already be generic over the workload config; fix them if not.

Acceptance: for `wide-4` with failure at the last step, path D parallel makespan is measurably lower than `compMode=lifo` (assert ≥ 25% lower at `workScale=1`; if the assertion fails, record numbers and stop to report, since it may indicate LocalStack overhead dominates).

---

### Phase 8: Fault-injection harness, load generator, metrics tooling

**Goal:** one reusable harness that runs any path × workload × fault plan and derives every metric from `SagaTrace`.

Files: `harness/run_experiment.py, derive.py, consistency.py, load.py, coupling.py, cost.py, pricing.json`, `experiments/configs/smoke.json`, `experiments/configs/full.json`.

Tasks:
1. `run_experiment.py --config X`: config lists paths, workloads, `workScale` values, a failure plan, repetitions, warm-up count, seed. Failure plan (default for `full.json`, per path per workload): 60 injected failures = 20 at Payment (`PaymentDeclined`), 20 at Inventory (`InventoryShortage`), 20 at Notification; plus 10 transient compensation failures (`compFailFirstN=1`); plus, path D only, 10 `leaderFault=crash_after:1` (reported separately, not in cross-path comparisons). **Runs are interleaved across paths in randomized order** (seeded) to avoid drift. Discard the first 10 runs per path as warm-up (still stored, flagged `warmup=true`). Write one JSONL line per run to `results/raw/<runTag>.jsonl`.
2. `derive.py`: from `SagaTrace`, compute the §3.5 metrics per run.
3. `consistency.py`: after a failed run reaches terminal state, assert the invariant: every step is in {COMPENSATED, FAILED (not compensated), never-run}; none remain COMPLETED; run status COMPENSATED; `compApplied ≤ 1` for all steps (no double effect). Also a negative test: deliberately corrupt a run's data and confirm the checker flags it.
4. `load.py`: open-loop generator at fixed rate (default 5 sagas/s for 60 s, 10% randomly failing at random depth, seeded), measure throughput and p50/p95 happy latency per path. Note the rate must be one the LocalStack host sustains; calibrate in the smoke run and record it.
5. `coupling.py` (reports per path, plus per service where relevant):
   - A: number of distinct Lambda ARN references in the ASL.
   - B: number of EventBridge rules targeting each service on `saga-bus-b` (and the total).
   - C: ASL refs (core) and rules (edge), reported separately and summed.
   - D: steady-state rules on `saga-bus-d` that match forward events (the `CompensationNeeded` fan-in rule is listed separately), and the **orchestrator static-reference count**, which must be 0, evidenced by the Phase 5 static test passing.
6. `cost.py` + `pricing.json`: units are Lambda invocations and billed GB-seconds, EventBridge events, Step Functions state transitions, DynamoDB read/write units (conditional writes that fail still consume write units). **Do not hard-code prices from memory:** look up current AWS list prices (note: DynamoDB on-demand prices changed in late 2024, so verify), record each value with source URL and retrieval date in `pricing.json`. Cost per 1,000 transactions is computed from the counted units of a mixed run (10% failures). If S8 failed, derive Step Functions transitions from the ASL path instead.
7. A `README` section "Running experiments" with exact commands.

Acceptance:
- `python harness/run_experiment.py --config experiments/configs/smoke.json` (2 sagas per path per scenario, `order` only) completes and writes JSONL + `results/summary.csv`.
- `pytest tests/phase8 -q` passes including the corrupted-run negative test and a derive test on a synthetic trace with known timestamps.
- `python harness/coupling.py` and `python harness/cost.py --run <runTag>` print tables for all implemented paths.

---

### Phase 9: SimPy simulator

**Goal:** characterize the election + compensation scheduler beyond what LocalStack can show. Not used for the headline numbers.

Files: `sim/model.py, sim/dags.py, sim/run.py, sim/plots.py`, `tests/phase9/`.

Tasks:
1. `sim/dags.py`: DAG generators: chain, wide fan (width k), layered random (depth, width, edge density), diamond, plus the real `order`, `trainticket`, `wide-*` shapes. Use `common/core/dag.py` for dependency semantics so there is a single definition.
2. `sim/model.py`: SimPy processes for: N participants racing a conditional-write lease (first arrival at the "table" wins; arrival times drawn from a latency distribution: constant, lognormal, heavy-tailed), lease TTL and heartbeat, leader crash probability *p* (leader dies mid-rollback), watcher takeover after expiry, concurrent sagas contending for one shared service pool (concurrent-failure rate λ), compensation durations drawn per node.
3. `sim/run.py --sweep default --seed S`: sweeps DAG width 1–8, depth 1–6, participants 2–16, latency distribution, λ, crash probability. Output CSVs in `results/sim/` and plots: election overhead vs participants, makespan reduction (parallel vs LIFO) vs width, re-election count vs crash probability.
4. Calibration (informational, not a gate): run the simulator with the measured LocalStack timings for `order` and report the predicted-vs-measured compensation latency ratio in `results/sim/calibration.md`.

Acceptance:
- Deterministic: the same seed gives identical CSVs (`pytest` checks hash equality).
- Property tests: with constant latency and a chain DAG, parallel makespan equals LIFO makespan; with an all-independent DAG of n nodes of equal duration d, parallel makespan ≈ d + election overhead and LIFO ≈ n·d.
- The sweep completes in under 10 minutes on a laptop.

---

### Phase 10: Frozen analysis plan, full experiment run, provenance

**Goal:** collect the real data once, under a pre-committed analysis plan, with enough provenance that every number in the paper can be reproduced and audited.
**Why:** deciding which comparisons matter *after* seeing results invites cherry-picking. A reviewer will ask. The plan is committed before the full run and the run's git hash is recorded.

Tasks:
1. **Prerequisite gate.** `docs/ANALYSIS_PLAN.md` (template in Phase 11, §11.1) must be committed and **approved by a human** before `full.json` is run. Record its commit hash in the run manifest.
2. Add `harness/manifest.py`, hooked into `run_experiment.py`, writing `results/raw/<runTag>.manifest.json` automatically: git commit and dirty flag; LocalStack version (health endpoint); host CPU count, RAM, OS, Docker version; Python and library versions; SHA-256 of the config file and of `ANALYSIS_PLAN.md`; seed; start/end timestamps; counts of runs, warm-ups, timeouts, and errors.
3. Run `experiments/configs/full.json`: 4 paths × workloads {`order`, `trainticket`, `wide-4`} at `workScale=1`; plus one `workScale` ∈ {0, 3} sensitivity run on `order`; plus a **load sweep** at offered rates {2, 5, 10} sagas/s (calibrate the top rate in the smoke run so the host is not saturated; record the choice). Keep raw JSONL under `results/raw/`.
4. Failed or timed-out runs (no terminal state within 60 s) are **kept** and counted as right-censored at 60 s. They are never silently dropped.
5. Append one entry per run to `docs/EXPERIMENT_LOG.md`: date, runTag, config name, wall-clock duration, anomalies seen (LocalStack restarts, host load, retries), and anything a reader would need to judge validity.
6. Optional stretch, if time allows and a human approves: A-parallel (Step Functions `Parallel` in the Catch path) and B-fanout variants, run as extra paths `A-par`, `B-fan` under the same plan.

Acceptance:
- `results/raw/<tag>.jsonl` and `<tag>.manifest.json` exist; run counts equal the config's expectation; timeouts are counted in the manifest.
- `docs/EXPERIMENT_LOG.md` has an entry for each run.
- No code changed between the manifest's commit and the run (dirty flag false).

---

### Phase 11: Research-paper assets (figures, tables, statistics, text numbers)

**Goal:** from the raw data alone, one command regenerates every figure, table, statistic, and in-text number the paper needs, in publication-ready form. Humans write the interpretation; the tooling writes only facts.

Single entry point: `python paper/build_assets.py --runTag <tag>`.

#### 11.1 Analysis plan template (`docs/ANALYSIS_PLAN.md`, written before Phase 10 and approved by a human)

Must contain, filled in with final choices:
- **Hypotheses** (derived from the proposal's research question):
  - H1: On workloads and failure depths where the compensation DAG has width ≥ 2 (order at Notification; `wide-4`; `wide-6` if run), D's median compensation latency is lower than A's, B's, and C's.
  - H2: Where the DAG is a chain (order at Payment and Inventory), D's median compensation latency is not lower than the baselines'. Expected overhead = election time. State the margin δ (e.g., 20% of the baseline median) within which a difference is considered "no practical difference".
  - H3 (ablation): D-parallel makespan < D-LIFO makespan where width ≥ 2, and equal within δ where the DAG is a chain.
  - H4: D's steady-state coupling equals B's, and D's orchestrator static-reference count is 0.
  - H5: D's recovery consistency is no lower than B's, including under leader-crash faults.
- **Primary comparisons** (these get Holm correction): D vs A, D vs B, D vs C on compensation latency, per workload × failure depth cell; D-parallel vs D-LIFO per cell. Everything else is labeled *exploratory* in every table and figure caption.
- **Statistics:** unit of analysis is one saga run. Descriptives: n, median, IQR, p95. Intervals: 95% percentile bootstrap CI on the median, 10,000 resamples, fixed seed. Pairwise: two-sided Mann-Whitney U, Holm-adjusted across primary comparisons, α = 0.05. Effect sizes: Cliff's delta and the Hodges-Lehmann median difference with bootstrap CI. Censored runs (timeouts) enter the ranks at 60 s and are counted in every table's n column.
- **Exclusions:** only the warm-up runs (first 10 per path). No outlier removal. Any other exclusion needs a human-approved note in `EXPERIMENT_LOG.md`.
- **Sensitivity:** `workScale` ∈ {0, 1, 3}. State which conclusions are expected to be robust to it.

#### 11.2 Statistics module

`paper/stats.py`: `bootstrap_ci_median`, `mann_whitney`, `cliffs_delta`, `hodges_lehmann`, `holm_adjust`. Pure functions, seeded, no plotting. Use `numpy` and `scipy`.

#### 11.3 Figures (matplotlib; every figure also saved with its plotted data)

Style, applied by one `paper/style.py` used by all figures:
- Colorblind-safe Okabe-Ito colors, fixed per series everywhere: A `#0072B2`, B `#E69F00`, C `#009E73`, D `#D55E00`, D-LIFO `#CC79A7` (plus hatch), A-par/B-fan (if run) lighter variants with dashed outlines.
- Widths: 3.4 in (single column) or 7.0 in (double column); font size 8-9 pt; no title inside the figure (the caption carries it); axis labels with units; direct labels over legends where there are ≤ 4 series.
- Output per figure: `paper/figures/<id>.pdf` (vector), `<id>.png` (300 dpi), `paper/figures/data/<id>.csv` (the exact plotted data, including n), and `<id>.caption.md` (factual draft: what is plotted, units, n per series, CI method, primary vs exploratory. **No interpretive claims**).

| ID | Figure | Type, axes, source |
|---|---|---|
| F1 | Architecture of paths A, B, C, D | Graphviz, generated from the real ASL and the rule sets (not hand-drawn), so the figure cannot disagree with the code. One panel per path, normal flow and compensation flow styled differently. |
| F2 | Compensation DAGs per workload and failure depth | Graphviz, generated from `common/workloads.py`. Shows which nodes are compensated for each failure depth and the width, plus the LIFO order vs the parallel layers. |
| F3 | Representative compensation timelines | Gantt chart from `SagaTrace`: one saga per path, same scenario (order at Notification; `wide-4` at last step). Pick the run whose compensation latency is closest to the cell median (deterministic rule). Show election, lease-acquire, and each compensation as bars; the overlap in D is the visual point. |
| F4 | Compensation latency distributions | Violin + strip + median marker, x = path, y = ms, facets = workload × failure depth. Right-censored runs drawn as open markers at 60 s. |
| F5 | Ablation: parallel vs LIFO in D | Grouped bars, x = failure depth (and DAG width for `wide-*`), y = median makespan (ms) with 95% CI; secondary panel: % reduction with CI. |
| F6 | Pareto: latency vs coupling | Scatter, x = coupling score (definition in Phase 8), y = median compensation latency (ms), one point per path with CI bars, one panel per workload; the non-dominated set outlined. |
| F7 | Cost of the election in D | Stacked bars per scenario: election_time + scheduling_makespan; and a histogram of election_time with participant count annotated; counts of `LEASE_LOST` and `WATCHER_RETRY`. |
| F8 | Throughput and latency under load | Lines, x = offered rate (sagas/s), y = (a) achieved throughput, (b) p95 happy-path latency, one line per path. |
| F9 | Cost per 1,000 transactions | Stacked bars by component (Lambda, EventBridge, Step Functions, DynamoDB), watcher/idle Lambda time shown as a separate hatched segment for D. |
| F10 | Recovery consistency and leader crash | (a) % consistent per path; (b) histogram of takeover time (`LEASE_TAKEOVER.ts − crash time`) for D's leader-crash runs, with the theoretical bound `LEASE_TTL_MS + WATCH_JITTER_MS` marked. |
| F11 | Sensitivity to simulated work | Lines, x = `workScale` (0, 1, 3), y = median compensation latency, one line per path. |
| F12 | Simulator results (appendix) | (a) makespan reduction vs DAG width (parallel vs LIFO), (b) election overhead vs participants by latency distribution, (c) re-elections vs crash probability, (d) predicted-vs-measured calibration scatter with y = x line. |

#### 11.4 Tables (each emitted as CSV and as LaTeX `booktabs` `.tex`)

| ID | Table | Content |
|---|---|---|
| T1 | Related work comparison | Template only, filled by the Documentation lead: rows = [1]–[6] and this work; columns = coordinator fixed or elected, always-on or triggered, scope (partitioning, consensus, compensation scheduling), evaluation. **Marked "to be completed after the full-text check" until §6 item 1 is resolved.** |
| T2 | Design summary of the four paths | Structural facts generated from the code (steps coordinated centrally, rules, retry policy, lease constants). |
| T3 | Main results | Per workload: for each path, n, median [95% CI], p95 for compensation latency, happy latency, throughput, cost per 1,000 txns, coupling, consistency %. Split by failure depth for latency. |
| T4 | Ablation by failure depth | D-parallel vs D-LIFO: n, medians [CI], difference, % reduction [CI], Cliff's delta, Holm-adjusted p. Rows with no expected gain are included and not hidden. |
| T5 | Primary pairwise comparisons | Every primary comparison from the analysis plan: Hodges-Lehmann difference [CI], Cliff's delta, raw and Holm-adjusted p, verdict word limited to: "lower", "higher", "no significant difference". Exploratory rows are in a separate block. |
| T6 | Coupling breakdown | Per path, per service and per bus; the D orchestrator static-reference count and the test that proves it. |
| T7 | Cost model | Price table with source URLs and retrieval dates, counted units per 1,000 txns per path, resulting cost. |
| T8 | Fault and consistency results | Per path: faults injected by type, runs consistent, runs timed out, duplicate-delivery events ignored, leader-crash recoveries. |
| T9 | Threats to validity | From §5 with measured values filled in (e.g., how much LocalStack overhead, from the `workScale=0` run). |
| T10 | Experimental setup | From the manifest: host, versions, LocalStack version, constants from `common/policy.py`, workloads and timings, seeds, run counts. |

#### 11.5 In-text numbers and skeleton

- `paper/numbers.json` and `paper/numbers.tex`: every headline number as a named value / LaTeX macro (e.g. `\numOrderNotifMedianD`, `\numAblationReductionWideFour`). Each carries its CI and n. Paper text should use the macros so figures and prose cannot drift.
- `paper/results_skeleton.md`: section outline for Results (Setup; Primary comparisons H1–H5; Ablation; Coupling; Cost; Load; Faults and consistency; Sensitivity; Simulator), each with the relevant figure/table IDs and `{{placeholders}}` filled from `numbers.json`. The generated sentences are **descriptive only**: a sentence may state a number, its interval, and one of the three verdict words from T5. Interpretation, motivation, and conclusions are left blank for the authors.
- `paper/manifest_for_paper.md`: copy of the run manifest formatted as the "Experimental setup" paragraph (host, versions, seeds, counts).

#### 11.6 Reproducibility bundle

`paper/artifact/` (built by `build_assets.py --bundle`): raw JSONL, manifest, configs, `ANALYSIS_PLAN.md`, `pricing.json`, a `REPRODUCE.md` with exact commands (setup → run → build assets), and a `SHA256SUMS`.

Acceptance (`pytest tests/phase11 -q`, plus the command below):
- `stats.py` against known values: bootstrap CI covers the true median in ≥ 93% of 200 synthetic datasets; Cliff's delta on hand-computed samples; Holm adjustment matches a textbook example; Hodges-Lehmann matches a hand-computed case.
- Figure builders run on a small synthetic raw file and produce `.pdf`, `.png`, `.csv`, `.caption.md` for every figure ID that has data.
- For every figure, the number of rows in its data CSV equals the n stated in its caption; for every number macro, `numbers.tex` equals `numbers.json`.
- A test confirms the primary-comparison list in T5 is exactly the list in `ANALYSIS_PLAN.md` (no extra or missing comparisons).
- `python paper/build_assets.py --runTag <tag>` completes and `ls paper/figures` shows F1-F12 (F12 from the simulator output) and `ls paper/tables` shows T2-T10 (T1 as a template); `paper/artifact/SHA256SUMS` verifies.

---

## 5. Threats to validity (must appear in the report; Phase 11, table T9, fills them in)

1. **LocalStack is not AWS.** Absolute latencies reflect container emulation. Only relative comparisons and the structure of the results are meaningful, and cost is analytical.
2. **Baseline fairness (D9).** A and B compensate sequentially by default. A reviewer can argue they could parallelize; the optional stretch variants address this. B parallelizing would require each service to know dependency information locally, which is itself coupling.
3. **Limited parallelism width** in 4-step workloads (§2 table): the scheduler gains only at late failure depths. This is why 7B and the simulator exist.
4. **Simulated work time (D4)** is an experimental device; the `workScale=0` run quantifies pure overhead.
5. **Single-host clocks (D15)**.
6. **Watcher cost (D7):** losers of the election are billed while waiting; included in D's cost, and reported separately in the cost table.
7. **TrainTicket-derived, not TrainTicket (7A)**.
8. **Related-work claim** against Xue et al. [5][6] is unconfirmed until the full texts are read (see §6).

## 6. Items only a human can resolve (the agent must not act on these)

1. **Xue et al. [5][6] full text** (the Documentation lead): confirm whether their coordination is election-based, always-on versus triggered, and whether it targets compensation scheduling. The novelty claims depend on it.
2. Confirm that "cancel Order last" (`compensateAfter: ["*"]`) is the intended business rule. It determines whether the order workload can show any scheduler gain.
3. Confirm Phase 7B (synthetic wide-fan) is added to scope. It is not in the proposal; the recommended cut order if time is short is: stretch variants → 7A → SimPy sweep breadth. Never cut Paths A–D or Phase 4–5.
4. Decide whether the stretch baselines A-parallel and B-fanout are in or out of scope (mentor input).
5. Approve `docs/ANALYSIS_PLAN.md` (hypotheses, margin δ, primary comparisons) **before** the Phase 10 full run, and write the interpretation and conclusions in the paper. The tooling only produces facts.

## 7. Team mapping (for parallel execution after Phase 1)

| Role | Phases |
|---|---|
| Orchestration lead | P2, then P6 core, then A-parallel stretch |
| Choreography lead | P3, then P6 edge |
| Election & scheduling lead | P4, P5, then P9 |
| Testing & metrics lead | P1 (with all), P8, P10, P11 (stats, figures, tables, numbers) |
| Documentation lead | P0 audit review, P7A mapping, `ANALYSIS_PLAN.md` (§11.1), T1, results prose from `results_skeleton.md`, threats to validity, §6 item 1 |
