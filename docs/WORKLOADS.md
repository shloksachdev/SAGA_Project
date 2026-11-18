# Workload Specifications & Characterization

This document details the workload configurations, execution semantics, dependency graphs, and timing models supported across the SAGA benchmark harness.

---

## 1. The `order` Workload (Standard E-Commerce Baseline)

The `order` workload models a standard 4-step e-commerce checkout transaction.

### Services and Steps:
- **Order** (`Order` Lambda): Creates the customer order record in DynamoDB (`Orders` table).
  - Forward: `action="create"`, `status="ORDER_CREATED"`
  - Compensate: `action="cancel"`, `status="ORDER_CANCELLED"`
  - Dependencies: `compensateAfter: ["*"]` (Cancellation must occur last after all downstream resources are rolled back).
- **Payment** (`Payment` Lambda): Charges customer funds via credit card or digital wallet.
  - Forward: `action="charge"`, `status="PAYMENT_COMPLETED"`
  - Compensate: `action="compensate"`, `status="PAYMENT_COMPENSATED"`
  - Dependencies: `compensateAfter: []` (Independent compensation).
- **Inventory** (`Inventory` Lambda): Reserves stock items in the warehouse inventory system.
  - Forward: `action="reserve"`, `status="INVENTORY_RESERVED"`
  - Compensate: `action="release"`, `status="INVENTORY_RELEASED"`
  - Dependencies: `compensateAfter: []` (Independent compensation).
- **Notification** (`Notification` Lambda): Dispatches customer confirmation email or SMS.
  - Forward: `action="notify"`, `status="NOTIFICATION_SENT"`
  - Compensate: `action="unnotify"`, `status="NOTIFICATION_RETRACTED"`
  - Dependencies: `compensateAfter: []`

### Timing & Durations:
- Forward simulated execution time: `150 ms` (jitter `30 ms`).
- Compensation simulated execution time: `150 ms` (jitter `30 ms`).

### Compensation Concurrency:
When failure occurs at Notification, Payment and Inventory are independent (`compensateAfter: []`), allowing Path D to execute their compensations concurrently. Order waits for all other services (`compensateAfter: ["*"]`).

---

## 2. The `trainticket` Workload (TrainTicket-Derived)

> [!NOTE]
> **Nature of the Workload (Transparency Statement per SPEC §4 Phase 7A Task 3):**
> This is a **shape-level port** reflecting the booking, payment, seat allocation, and notification semantics, dependencies, and timing profiles of the TrainTicket benchmark. It is executed on the benchmark's standardized four services rather than as an in-place deployment of the upstream multi-language TrainTicket repository. Experimental reports must designate this workload as **TrainTicket-derived**.

### Semantic Mapping:
- **Order** (`Order` Lambda): `book` (Seat booking reservation in DynamoDB).
  - Forward: `action="book"`, `status="ORDER_CREATED"`
  - Compensate: `action="cancel"`, `status="ORDER_CANCELLED"`
  - Dependencies: `compensateAfter: ["*"]` (Booking cancel waits for all downstream rollbacks).
- **Payment** (`Payment` Lambda): `pay` (Ticket fee payment).
  - Forward: `action="pay"`, `status="PAYMENT_COMPLETED"`
  - Compensate: `action="refund"`, `status="PAYMENT_COMPENSATED"`
  - Dependencies: `compensateAfter: ["Inventory"]` (**Strict business rule: refund is permitted only after the allocated seat has been successfully released back into inventory**).
- **Inventory** (`Inventory` Lambda): `seat-allocate` (Seat inventory assignment).
  - Forward: `action="seat-allocate"`, `status="INVENTORY_RESERVED"`
  - Compensate: `action="release"`, `status="INVENTORY_RELEASED"`
  - Dependencies: `compensateAfter: []` (Seat release may proceed immediately).
- **Notification** (`Notification` Lambda): `confirmation` (Ticket issuance confirmation).
  - Forward: `action="confirmation"`, `status="NOTIFICATION_SENT"`
  - Compensate: `action="unnotify"`, `status="NOTIFICATION_RETRACTED"`
  - Dependencies: `compensateAfter: []`

### Timing & Durations:
- `Payment` (pay / refund): `300 ms` simulated work (jitter `30 ms`).
- `Inventory` (seat-allocate / release): `200 ms` simulated work (jitter `30 ms`).
- `Order` (book / cancel): `100 ms` simulated work (jitter `30 ms`).
- `Notification` (confirmation / unnotify): `100 ms` simulated work (jitter `30 ms`).

### Compensation Dependency Structure:
Unlike the e-commerce workload where Payment and Inventory are symmetric and mutually independent, TrainTicket exhibits asymmetric dependencies:
1. **Layer 0**: `Inventory` compensation (seat release) executes first (`compensateAfter: []`).
2. **Layer 1**: `Payment` compensation (refund) executes only after `Inventory` completes (`compensateAfter: ["Inventory"]`).
3. **Layer 2**: `Order` compensation (cancel booking) executes last after all prior layers have finished (`compensateAfter: ["*"]`).

This allows empirical verification of dynamic DAG scheduling: Path D dynamically constructs the directed graph from step metadata alone without any hardcoded workload knowledge, strictly honoring `Payment -> Inventory`.
