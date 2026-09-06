# Compensation-Triggered Orchestrator Election over a Choreographed Saga Base

**Project Report**
Team size: 5 · Cloud provider: AWS via LocalStack (no AWS account required) · Estimated cost: $0

---

## 1. Executive Summary

Microservice architectures cannot rely on cross-service ACID transactions, since every service owns its own data store. The Saga pattern addresses this by breaking a distributed transaction into local transactions, each paired with a compensating action for failure. Two implementation styles dominate practice — **orchestration** (a central coordinator directs the sequence) and **choreography** (services react to each other's events with no central authority) — and every source we reviewed converges on the same conventional wisdom: real systems use a manually-drawn hybrid of the two, fixed once at design time.

This project replaces that manual, static split with a mechanism: a lightweight, on-demand leader election that produces a **temporary orchestrator only when a saga instance actually needs one**, layered on top of a fully choreographed base. We implement and compare four variants of the same order-processing workflow — pure orchestration, pure choreography, a static hybrid, and our proposed election-triggered adaptive hybrid — on identical infrastructure, entirely emulated locally via LocalStack.

---

## 2. Problem Statement

In a single database, a transaction is atomic — either everything commits or nothing does. Once each service in a system owns its own database, that guarantee disappears: a single business operation (e.g., placing an order) now spans several independently-failing services, and there is no built-in way to roll all of them back together if one step fails.

The Saga pattern solves this by making each step *locally* transactional and pairing it with an explicit **compensating action** — e.g., a payment charge is undone with a refund, not with a database rollback. The open design question is *who decides the order of steps and who triggers compensations*: a central coordinator, or the services themselves reacting to events. Industry guidance treats this as a binary, or at best a fixed hybrid decided once. This project asks whether that decision can instead be made dynamically, per failure, without paying for a coordinator that sits idle the rest of the time.

---

## 3. Related Work & the Novelty Gap

A plain comparison of orchestration vs. choreography is well-trodden ground — it appears in industry posts contrasting AWS Step Functions and EventBridge directly, broader architecture write-ups on the trade-off, and a published IEEE conference paper comparing the two styles in microservice architectures. Every one of these sources repeats the same conclusion: large systems use a hybrid split between the two styles — but none of them build or measure that hybrid quantitatively, and in every case the split is decided manually, once, at design time (Akka's saga framework, for instance, exposes this as a static per-workflow configuration flag).

Two papers sit closer to this project's actual contribution and are treated as primary related work rather than background:

- **Xue, Liu, Liu & Yao (2019)** propose an automatic technique for partitioning a service composition for decentralized execution.
- **Xue, Deng, Liu & Yan (2021)** study runtime coordination mechanisms for Saga-based microservice compositions that lack an independent central coordinator, evaluated across two experiments.

Both address closely adjacent problems. Based on the published abstracts, this project's contribution differs in two specific ways: (a) the coordination mechanism is triggered narrowly — only at the moment a compensation begins — rather than being a standing runtime protocol, and (b) the elected coordinator's job is specifically to schedule compensating actions as a dependency-aware parallel plan, not merely to reach agreement on step ordering.

> **Open item:** the team currently has abstract-level access only to both Xue et al. papers (paywalled). Full text must be obtained (library access or direct author request) before these differentiation claims are finalized, to confirm whether their mechanism is election-based, always-on vs. triggered, and whether it targets compensation scheduling specifically.

---

## 4. Research Question & Objectives

**Primary research question:** For an event-driven order-processing workflow, does a choreographed base with compensation-triggered orchestrator election and dependency-aware parallel compensation scheduling reduce recovery latency relative to pure orchestration, pure choreography, and a statically-partitioned hybrid — without introducing a permanent central coordinator or a separate always-on controller?

**Optimization objective:** the proposed design (Path D) is optimized primarily to minimize **compensation makespan** (time from failure detection to full rollback completion), subject to a **coupling ceiling** — the elected orchestrator role must not accumulate standing references the way a fixed orchestrator would — with steady-state infrastructure cost as a tie-breaker. Where objectives conflict across paths, results are reported as a Pareto comparison (latency vs. coupling) rather than collapsed into a single weighted score.

**Concrete objectives:**

1. Implement four variants of the same workflow (Order → Payment → Inventory → Notification): pure orchestration, pure choreography, static hybrid, and the proposed election-triggered adaptive hybrid.
2. Build a compensation-triggered leader election mechanism using a conditional write as a lease, so an orchestrator exists only for the duration of a single saga instance's rollback.
3. Build a dependency-graph compensation scheduler that runs independent compensating actions concurrently, in contrast to naive LIFO (reverse-order) compensation.
4. Inject controlled failures (payment decline, inventory shortage) and measure recovery latency, election overhead, coupling, throughput, and cost across all four variants.
5. Isolate the scheduler's contribution with an ablation: naive sequential compensation vs. dependency-aware parallel compensation, both run by the same elected orchestrator.
6. Validate all four variants on two workloads: the group's own order-processing saga, and a compensation-heavy subgraph of TrainTicket (a widely-used open-source microservices benchmark), to ground results in a workload used in prior academic research rather than only one the team invented.

---

## 5. System Architecture

### 5.1 Shared infrastructure

All four variants are built on identical infrastructure, deployed once and reused across every path:

```
 DynamoDB: orders table      (saga instance state — which steps completed)
 DynamoDB: leases table      (Path D only — the election mechanism)
 EventBridge: custom bus     (used by B, the edge of C, and all of D)
 Step Functions             (used by A, and the core of C)

 Lambda microservices: [Order]  [Payment]  [Inventory]  [Notification]
   each exposes a normal handler and a compensating handler
```

Everything runs inside Docker via **LocalStack**, which emulates Lambda, DynamoDB, EventBridge, and Step Functions locally. No AWS account or spend is required — the AWS SDK code is written identically to what would run on real AWS, so redeploying after the project is a configuration change, not a rewrite.

### 5.2 Path A — Pure orchestration

```
                 +---------------------------+
                 |      Step Functions       |
                 |   (central coordinator)   |
                 +-------------+-------------+
                                |
        +---------+------------+------------+---------+
        v         v            v            v
    [Order]   [Payment]   [Inventory]  [Notification]

  On failure: Catch state -> compensating states run in reverse order
```

A single state machine (Amazon States Language) defines a Task state per service, with `Retry` blocks for transient failures and `Catch` blocks that route to compensating states. Every service only needs to expose an API the coordinator can call — the entire workflow logic lives in one file, readable top to bottom.

### 5.3 Path B — Pure choreography

```
                    +------------------------+
                    |   EventBridge Bus      |
                    +------------------------+
                     ^     |   ^     |   ^   |
                     |     v   |     v   |   v
                 [Order]  [Payment]  [Inventory]  [Notification]

  No coordinator exists. Each service reacts to the prior step's
  event and publishes its own event (or a compensating event) when done.
```

Per-service EventBridge rules replace the state machine. The "workflow" is not defined anywhere as a single artifact — it's the emergent sum of every service's event subscriptions, which is what makes this style loosely coupled but harder to trace.

### 5.4 Path C — Static hybrid (baseline)

```
   Orchestrated core (Step Functions)        Choreographed edge (EventBridge)
   +------------------------------+          +---------------------------+
   |  [Order] -> [Payment] -> [Inventory] --event--> [Notification]      |
   +------------------------------+          +---------------------------+
```

Payment and Inventory — tightly coupled, money-critical, order-sensitive — are orchestrated via Step Functions. Notification — a side effect nobody blocks on — stays choreographed via EventBridge. The split is fixed at deploy time and never changes.

### 5.5 Path D — Compensation-triggered election (proposed contribution)

```
 Normal operation (identical to Path B):
    EventBridge bus <-> [Order] [Payment] [Inventory] [Notification]

 On failure:
    "compensation needed" event published
            |
            v
    Candidate services race for a DynamoDB conditional-write lease
    scoped to this saga instance
            |
            v
    Winner becomes temporary orchestrator:
      - reads the `orders` table for which steps already completed
      - builds a compensation dependency graph
      - dispatches independent compensating actions in parallel
            |
            v
    Lease expires automatically once compensation completes
    (or times out -> triggers re-election if the winner dies mid-rollback)
            |
            v
    System returns to pure choreography for the next saga instance
```

Every step runs choreographed by default, identical to Path B. The structural difference from Path C is that **Path D has no fixed orchestrated core** — orchestration is an ephemeral role, assumed only during a rollback, only by whichever peer wins the election, only for that one saga instance. The lease is acquired with a DynamoDB `PutItem` guarded by a `ConditionExpression` (e.g. `attribute_not_exists(saga_id)`), which is atomic — so if five services race for the same lease simultaneously, exactly one succeeds, without needing a separate lock service. A TTL attribute on the lease item makes it self-expire, which is also the re-election trigger if the elected node fails before finishing.

---

## 6. Workflow Walkthroughs

### 6.1 Happy path (no failures)

Across all four paths, the business logic is the same: an order is placed, payment is charged, inventory is reserved, and a confirmation notification is sent. What differs is only *how the next step gets triggered*:

| Path | How Payment knows Order succeeded | How Notification gets triggered |
|---|---|---|
| A | Step Functions calls it directly | Step Functions calls it directly |
| B | Reacts to an `OrderPlaced` event | Reacts to an `InventoryReserved` event |
| C | Step Functions calls it directly | Reacts to an `InventoryReserved` event |
| D | Reacts to an `OrderPlaced` event | Reacts to an `InventoryReserved` event |

### 6.2 Failure & compensation workflow

Say Payment fails after Order and (in some paths) other steps have already completed. Each path recovers differently:

- **Path A:** the state machine's `Catch` block fires immediately, and Step Functions runs the compensating states in reverse order — deterministic, but always sequential and always through the same central coordinator.
- **Path B:** the failing service publishes a compensation event; every service that completed a step for this instance reacts independently, running its own compensating handler — no single place coordinates the order, so parallel and sequential compensations are indistinguishable from the outside.
- **Path C:** if the failure happens in the orchestrated core (Payment/Inventory), Step Functions compensates it directly; if it's on the choreographed edge (Notification), that recovers the same way as Path B.
- **Path D:** the failure triggers the election described in §5.5 — a temporary orchestrator is elected within milliseconds, reads exactly which steps need undoing for this instance, and runs the independent ones in parallel rather than serially. Once done, the system has no standing coordinator again.

---

## 7. Implementation Plan on LocalStack

1. **Spin up LocalStack** (Docker, with lambda/dynamodb/events/states/logs enabled) and install `awslocal` so every CLI/SDK call targets it by default. Verify the Step Functions → EventBridge emulation path early, since it has had version-specific gaps and both Path A and Path C depend on it.
2. **Deploy the shared building blocks**: the four Lambdas, the `orders` table, the `leases` table, and the EventBridge bus — once, via the same IaC tooling, so every path points at identical infrastructure.
3. **Build Path A**: a Step Functions state machine with Retry/Catch and compensating states.
4. **Build Path B**: EventBridge rules per service, with compensating-event publishers and handlers.
5. **Build Path C**: reuse Path A's state machine minus Notification, plus Path B's Notification wiring unchanged.
6. **Build Path D part 1 (election)**: a Lambda triggered by the "compensation needed" event, attempting a conditional `PutItem` against the leases table, with a TTL for auto-expiry and re-election.
7. **Build Path D part 2 (scheduler)**: the election winner reads completed steps, builds the dependency graph, and dispatches parallel compensations — plus a naive-LIFO version behind the same election, toggleable by config, for the ablation.
8. **Instrument uniformly**: structured JSON logs (or a shared metrics table) with a saga correlation ID across all four paths, and one shared fault-injection point so failure conditions are identical across paths.

A discrete-event simulator (Python + SimPy) of just the election mechanism and compensation scheduler — decoupled from AWS/LocalStack — is built separately, to sweep DAG shapes, cluster sizes, and concurrent-failure rates beyond what fault injection on LocalStack alone can cover. It characterizes the algorithm; it does not produce the headline benchmark numbers.

---

## 8. Evaluation Methodology & Metrics

All metrics are computed from one shared log schema (`saga_id`, `path`, `event`, `timestamp`, `step`), so the same query logic works across all four paths.

| Metric | How it's measured |
|---|---|
| **Compensation latency** | Failure detected → full rollback complete. For Path D specifically, split into election time (failure → lease acquired) and parallel-scheduled makespan (lease acquired → rollback complete), to show *why* it wins or loses. |
| **Coupling score** | A static count off deployed configuration, not a runtime metric: direct resource references in the state machine (A), event subscriptions per service (B, D), or both counted separately for the orchestrated core and choreographed edge (C). |
| **Traceability** | Percentage of saga instances whose full step order and outcome can be reconstructed purely from stored logs. A gets this for free from Step Functions execution history; D needs the election/lease log added to correlation-ID tracing to match it. |
| **Throughput** | Same load generator across all paths; Path D is additionally measured under concurrent failures specifically, since lease contention during simultaneous rollbacks is the one scenario that could degrade it relative to the others. |
| **Cost per 1,000 transactions** | Computed analytically from resource-usage counts (state transitions, event counts, Lambda invocations, conditional writes) applied to published AWS list pricing, since LocalStack itself is free. |
| **Recovery consistency** | Correct rollbacks ÷ total injected failures, across 50+ injected failures per path. Path D additionally breaks out the concurrent-failure / re-election cases as their own sub-score. |

**Ablation (within Path D only):** naive sequential (LIFO) compensation vs. dependency-aware parallel compensation, both run by the same elected orchestrator, measured as reduction in compensation makespan.

**Workloads:** every metric above is collected twice — once on the team's own order-processing saga, once on a ported TrainTicket `book → pay → seat-allocate → cancel/refund` subgraph — so results aren't an artifact of one workflow's shape.

**Supplementary robustness study:** the SimPy simulator sweeps DAG width, cluster size, and concurrent-failure rate to produce election-overhead and makespan-reduction curves beyond what LocalStack trials alone can cover, reported as an appendix rather than part of the headline comparison.

---

## 9. Team Roles & Responsibilities

| Role | Responsibilities |
|---|---|
| **Orchestration lead** | Build Path A: Step Functions state machine, Lambda microservices, compensating states. |
| **Choreography lead** | Build Path B: EventBridge bus, event rules, per-service compensating handlers. Also builds Path C's edge (Notification), reusing this work. |
| **Election & scheduling lead** | Build Path D's core contribution: the compensation-triggered leader election (DynamoDB lease) and the dependency-graph parallel compensation scheduler, plus the naive-LIFO comparison version. |
| **Testing & metrics lead** | Build the fault-injection harness and load generator; instrument all four paths identically; collect results. |
| **Documentation lead** | Own the related-work review — including resolving the open item on the two Xue et al. papers — paper write-up, results synthesis, and mentor presentation. |

---

## 10. Cost & Resources

All four paths run entirely on LocalStack — no AWS account, no billing, no cloud spend. Total project cost: **$0**. The only resource to manage is local machine capacity: running Lambda, DynamoDB, EventBridge, and Step Functions emulation simultaneously in Docker requires roughly 8GB+ of free RAM on at least one team member's machine, which should be verified early rather than assumed.

---

## 11. Expected Deliverables

1. Four working implementations (orchestration, choreography, static hybrid, election-triggered adaptive hybrid) with infrastructure-as-code.
2. A compensation-triggered leader election module and a dependency-aware parallel compensation scheduler, both reusable independently of the rest of the project.
3. A fault-injection and metrics harness, reusable across all four paths.
4. Results tables and charts comparing all four paths on every evaluation metric, plus the LIFO-vs-parallel compensation ablation.
5. A written report positioning this work against the Xue et al. papers once full text is confirmed, plus a short presentation.
6. A discrete-event simulator (SimPy) characterizing the election and compensation scheduler across DAG shapes, cluster sizes, and failure rates, independent of AWS/LocalStack.
7. A ported TrainTicket cancel/refund subgraph, usable as a second, externally-recognized workload beyond this project.

---

## References

1. EventBridge vs. Step Functions: When to choreograph and when to orchestrate — Medium, Apr 2026.
2. Coordinating distributed systems with the Saga Pattern on AWS — willdady.com.
3. Saga Orchestration vs. Choreography: Making the Right Trade-off in Event-Driven Systems — dev.to, Mar 2026.
4. Comparison of Choreography vs Orchestration Based Saga Patterns in Microservices — IEEE Conference Publication, IEEE Xplore.
5. G. Xue, D. Liu, J. Liu, S. Yao, "A process partitioning technique for constructing decentralized web service compositions," *Software: Practice and Experience*, 2019.
6. G. Xue, S. Deng, D. Liu, Z. Yan, "Reaching consensus in decentralized coordination of distributed microservices," *Computer Networks*, vol. 187, 107786, 2021. (Full text access pending — see §3.)
7. X. Zhou et al., "Benchmarking Microservice Systems for Software Engineering Research" (TrainTicket benchmark), ICSE 2018; open-source at github.com/FudanSELab/train-ticket.
8. LocalStack — local AWS cloud service emulator, localstack.cloud.
