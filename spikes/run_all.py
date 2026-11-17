"""
Purpose: Master test runner for all Phase 0 LocalStack spikes (S1 to S8).
Phase: Phase 0
"""

import sys
import os

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from spikes.spike_S1 import run as run_s1
from spikes.spike_S2 import run as run_s2
from spikes.spike_S3 import run as run_s3
from spikes.spike_S4 import run as run_s4
from spikes.spike_S5 import run as run_s5
from spikes.spike_S6 import run as run_s6
from spikes.spike_S7 import run as run_s7
from spikes.spike_S8 import run as run_s8

SPIKES = [
    {
        "id": "S1",
        "name": "EventBridge rule -> Lambda delivers $.detail as Lambda event",
        "fallback": "Use full event and unwrap in parse_event()",
        "fn": run_s1,
    },
    {
        "id": "S2",
        "name": "Step Functions -> Lambda with named-error Catch and Retry (IntervalSeconds 1)",
        "fallback": "Catch States.ALL only",
        "fn": run_s2,
    },
    {
        "id": "S3",
        "name": "Step Functions putEvents service integration",
        "fallback": "A tiny Lambda Task that publishes the event",
        "fn": run_s3,
    },
    {
        "id": "S4",
        "name": "DynamoDB conditional UpdateItem with epoch increment",
        "fallback": "Use GetItem + conditional PutItem with a version attribute",
        "fn": run_s4,
    },
    {
        "id": "S5",
        "name": "DynamoDB TransactWriteItems with ConditionCheck",
        "fallback": "Skip fencing transactions; rely on D8 idempotency only",
        "fn": run_s5,
    },
    {
        "id": "S6",
        "name": "Lambda invoking Lambda synchronously from inside container (4 concurrent)",
        "fallback": "Dispatch via CompensateStep events and have leader poll SagaSteps",
        "fn": run_s6,
    },
    {
        "id": "S7",
        "name": "EventBridge target RetryPolicy + DeadLetterConfig (SQS)",
        "fallback": "Implement retry-then-DLQ inside the Notification handler",
        "fn": run_s7,
    },
    {
        "id": "S8",
        "name": "sfn.get_execution_history returns state-entered events",
        "fallback": "Count transitions from the known ASL path",
        "fn": run_s8,
    },
]

def main():
    print("=" * 80)
    print("RUNNING PHASE 0 LOCALSTACK SPIKES (S1 - S8)")
    print("=" * 80)

    results = []
    for sp in SPIKES:
        sp_id = sp["id"]
        sp_name = sp["name"]
        print(f"\n--- Running Spike {sp_id}: {sp_name} ---")
        try:
            passed = sp["fn"]()
        except Exception as e:
            print(f"[{sp_id}] EXCEPTION: {e}")
            passed = False
        results.append({
            "id": sp_id,
            "name": sp_name,
            "passed": passed,
            "fallback": sp["fallback"],
        })

    print("\n" + "=" * 80)
    print("SPIKE RESULTS SUMMARY TABLE")
    print("=" * 80)
    header = f"{'Spike':<6} | {'Status':<6} | {'Verification Target':<50} | {'Fallback / Note'}"
    print(header)
    print("-" * 120)

    report_lines = [
        "<!--",
        "Purpose: LocalStack Spike findings, test outcomes, and fallbacks.",
        "Phase: Phase 0",
        "-->",
        "",
        "# LocalStack Findings & Spike Results (Phase 0)",
        "",
        "| Spike | Result | Verification Target | Fallback if FAIL / Action Taken |",
        "|---|---|---|---|",
    ]

    for r in results:
        status_str = "PASS" if r["passed"] else "FAIL"
        note = "Native behavior verified" if r["passed"] else f"Adopt fallback: {r['fallback']}"
        row = f"{r['id']:<6} | {status_str:<6} | {r['name']:<50} | {note}"
        print(row)
        report_lines.append(f"| {r['id']} | **{status_str}** | {r['name']} | {note} |")

    report_lines.append("")
    report_lines.append("## Architectural Decisions from Spike Findings")
    report_lines.append("")
    for r in results:
        if r["passed"]:
            report_lines.append(f"- **{r['id']} ({r['name']})**: PASSED. Proceed with native LocalStack capability as specified.")
        else:
            report_lines.append(f"- **{r['id']} ({r['name']})**: FAILED. Adopting fallback: *{r['fallback']}*.")

    findings_path = os.path.join(PROJECT_ROOT, "docs", "localstack_findings.md")
    with open(findings_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines) + "\n")
    print(f"\nWritten findings to {findings_path}")

    return 0

if __name__ == "__main__":
    sys.exit(main())
