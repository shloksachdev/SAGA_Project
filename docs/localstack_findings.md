<!--
Purpose: LocalStack Spike findings, test outcomes, and fallbacks.
Phase: Phase 0
-->

# LocalStack Findings & Spike Results (Phase 0)

| Spike | Result | Verification Target | Fallback if FAIL / Action Taken |
|---|---|---|---|
| S1 | **PASS** | EventBridge rule -> Lambda delivers $.detail as Lambda event | Native behavior verified |
| S2 | **PASS** | Step Functions -> Lambda with named-error Catch and Retry (IntervalSeconds 1) | Native behavior verified |
| S3 | **PASS** | Step Functions putEvents service integration | Native behavior verified |
| S4 | **PASS** | DynamoDB conditional UpdateItem with epoch increment | Native behavior verified |
| S5 | **PASS** | DynamoDB TransactWriteItems with ConditionCheck | Native behavior verified |
| S6 | **PASS** | Lambda invoking Lambda synchronously from inside container (4 concurrent) | Native behavior verified |
| S7 | **FAIL** | EventBridge target RetryPolicy + DeadLetterConfig (SQS) | Adopt fallback: Implement retry-then-DLQ inside the Notification handler |
| S8 | **PASS** | sfn.get_execution_history returns state-entered events | Native behavior verified |

## Architectural Decisions from Spike Findings

- **S1 (EventBridge rule -> Lambda delivers $.detail as Lambda event)**: PASSED. Proceed with native LocalStack capability as specified.
- **S2 (Step Functions -> Lambda with named-error Catch and Retry (IntervalSeconds 1))**: PASSED. Proceed with native LocalStack capability as specified.
- **S3 (Step Functions putEvents service integration)**: PASSED. Proceed with native LocalStack capability as specified.
- **S4 (DynamoDB conditional UpdateItem with epoch increment)**: PASSED. Proceed with native LocalStack capability as specified.
- **S5 (DynamoDB TransactWriteItems with ConditionCheck)**: PASSED. Proceed with native LocalStack capability as specified.
- **S6 (Lambda invoking Lambda synchronously from inside container (4 concurrent))**: PASSED. Proceed with native LocalStack capability as specified.
- **S7 (EventBridge target RetryPolicy + DeadLetterConfig (SQS))**: FAILED. Adopting fallback: *Implement retry-then-DLQ inside the Notification handler*.
- **S8 (sfn.get_execution_history returns state-entered events)**: PASSED. Proceed with native LocalStack capability as specified.
