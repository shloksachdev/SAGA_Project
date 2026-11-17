<!--
Purpose: Shared contracts copy from SPEC.md Section 3.
Phase: Phase 0
-->

# Shared Contracts (SPEC.md Section 3)

## 3.1 Saga envelope (input to any path, carried through every event and state)

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

## 3.2 DynamoDB tables (all created idempotently by `infra/provision.py`)

| Table | Key | Attributes |
|---|---|---|
| `SagaRuns` | `sagaId` (S) | `path, workload, runTag, status (RUNNING/COMPLETED/COMPENSATING/COMPENSATED/COMPENSATION_FAILED), startedAt, failedAt, failedStep, compensatedAt, stepCounter (N)` |
| `SagaSteps` | `sagaId` (S), `step` (S) | `status (COMPLETED/FAILED/COMPENSATING/COMPENSATED/COMP_FAILED), seq (N, completion order), completedAt, compensatorFn, compensateAction, compensateAfter (L), compensateOnFailure (BOOL), compInvocations (N), compApplied (N), compensatedAt` |
| `SagaLeases` | `sagaId` (S) | `ownerId, epoch (N), leaseExpiresAt (N), status (ACTIVE/DONE), electedAt` |
| `SagaTrace` | `sagaId` (S), `sk` (S = zero-padded ms + `#` + random suffix) | `event, step, actor, path, detail (M)` |

`seq` is assigned by an atomic `ADD stepCounter 1` on the `SagaRuns` item with `ReturnValues=UPDATED_NEW`. It defines "completion order" for LIFO.

## 3.3 Trace event names (exact strings; the metrics code depends on them)

`SAGA_STARTED, STEP_STARTED, STEP_COMPLETED, STEP_FAILED, SAGA_COMPLETED, COMP_NEEDED_PUBLISHED, ELECTION_START, LEASE_ACQUIRED, LEASE_LOST, LEASE_RENEWED, LEASE_TAKEOVER, WATCHER_RETRY, COMP_DISPATCHED, COMP_STARTED, COMP_COMPLETED, COMP_FAILED_ATTEMPT, COMP_DUPLICATE_IGNORED, SAGA_COMPENSATED, SAGA_COMPENSATION_FAILED, NOTIFICATION_DLQ, LAMBDA_INVOKE, LAMBDA_END, DDB_OPS, EVENTS_PUT, SFN_TRANSITIONS`

Rule for who writes `SAGA_COMPENSATED`: the component executing the final compensating action. In A, B and C this is the Order `cancel` handler. In D it is the leader, once the DAG drains.

## 3.4 Events (paths B, C-edge, D)

- Bus `saga-bus-{b|c|d}`. `source` = `saga.<service>` (lowercase). `detail` = the saga envelope plus `{step, result, ts}`.
- `detail-type` values: `SagaStarted, OrderCreated, PaymentCharged, PaymentFailed, InventoryReserved, InventoryFailed, NotificationSent, NotificationFailed, CompensationNeeded` (D only), and for path B compensation: `InventoryCompensated, PaymentCompensated, OrderCancelled`.
- Rule targets use input path `$.detail` so the handler receives the envelope directly. Add Lambda invoke permission for each rule.
- All new handler code must accept either a direct-invoke payload or an EventBridge-wrapped event (`common/events.py: parse_event()`).

## 3.5 Metric definitions (exact)

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
