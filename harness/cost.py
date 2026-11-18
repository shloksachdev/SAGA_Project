"""
Purpose: Analytical cost model for distributed sagas based on AWS list pricing (§3.5, Task 6).
Phase: Phase 8
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

PRICING_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pricing.json")


def load_pricing(filepath: str = PRICING_FILE) -> Dict[str, Any]:
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def calculate_run_cost(
    metrics: Dict[str, Any],
    pricing: Optional[Dict[str, Any]] = None,
    memory_mb: int = 128,
) -> Dict[str, float]:
    """
    Computes analytical USD cost from resource usage units for a single saga execution.
    """
    p = pricing or load_pricing()
    services = p.get("services", {})

    lambda_p = services.get("lambda", {})
    eb_p = services.get("eventbridge", {})
    sfn_p = services.get("step_functions", {})
    ddb_p = services.get("dynamodb", {})
    sqs_p = services.get("sqs", {})

    invocations = metrics.get("lambda_invocations", 0)
    duration_ms = metrics.get("lambda_duration_ms", 0.0)
    eb_events = metrics.get("eventbridge_events", 0)
    sfn_transitions = metrics.get("step_functions_transitions", 0)
    ddb_wru = metrics.get("dynamodb_wru", 0)
    ddb_rru = metrics.get("dynamodb_rru", 0)
    sqs_reqs = metrics.get("sqs_requests", 0)

    # 1. Lambda compute
    gb = memory_mb / 1024.0
    sec = duration_ms / 1000.0
    lambda_req_cost = invocations * lambda_p.get("request_unit_price", 0.0000002)
    lambda_compute_cost = (sec * gb) * lambda_p.get("gb_second_unit_price", 0.0000166667)
    lambda_total = lambda_req_cost + lambda_compute_cost

    # 2. EventBridge
    eb_total = eb_events * eb_p.get("event_unit_price", 0.000001)

    # 3. Step Functions
    sfn_total = sfn_transitions * sfn_p.get("transition_unit_price", 0.000025)

    # 4. DynamoDB
    ddb_w_cost = ddb_wru * ddb_p.get("wru_unit_price", 0.00000025)
    ddb_r_cost = ddb_rru * ddb_p.get("rru_unit_price", 0.00000005)
    ddb_total = ddb_w_cost + ddb_r_cost

    # 5. SQS
    sqs_total = sqs_reqs * sqs_p.get("request_unit_price", 0.0000004)

    total_cost = lambda_total + eb_total + sfn_total + ddb_total + sqs_total

    return {
        "lambda_invocations": invocations,
        "lambda_duration_ms": duration_ms,
        "lambda_cost": lambda_total,
        "eventbridge_events": eb_events,
        "eventbridge_cost": eb_total,
        "step_functions_transitions": sfn_transitions,
        "step_functions_cost": sfn_total,
        "dynamodb_wru": ddb_wru,
        "dynamodb_rru": ddb_rru,
        "dynamodb_cost": ddb_total,
        "sqs_requests": sqs_reqs,
        "sqs_cost": sqs_total,
        "total_cost": total_cost,
        "cost_per_1000": total_cost * 1000.0,
    }


def format_cost_table(path_costs: Dict[str, Dict[str, float]]) -> str:
    lines = [
        "| Path | Invocations | Lambda Cost | EB Events | EB Cost | SFN Transitions | SFN Cost | DDB Ops (W/R) | DDB Cost | Total / Txn | Cost / 1k Txns |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for path, c in sorted(path_costs.items()):
        ddb_ops_str = f"{c.get('dynamodb_wru', 0)} / {c.get('dynamodb_rru', 0)}"
        lines.append(
            f"| **{path}** | {c.get('lambda_invocations', 0):.1f} | ${c.get('lambda_cost', 0):.6f} | "
            f"{c.get('eventbridge_events', 0):.1f} | ${c.get('eventbridge_cost', 0):.6f} | "
            f"{c.get('step_functions_transitions', 0):.1f} | ${c.get('step_functions_cost', 0):.6f} | "
            f"{ddb_ops_str} | ${c.get('dynamodb_cost', 0):.6f} | "
            f"${c.get('total_cost', 0):.6f} | **${c.get('cost_per_1000', 0):.4f}** |"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Calculate saga coordination costs from pricing model")
    parser.add_argument("--run", dest="run_tag", default=None, help="Run tag to evaluate from results/raw or DynamoDB")
    parser.add_argument("--file", dest="file_path", default=None, help="Path to raw JSONL results file")
    args = parser.parse_args()

    pricing = load_pricing()
    print(f"[Cost Model] Loaded AWS list pricing (retrieval date: {pricing.get('retrieval_date')}, region: {pricing.get('region')})")

    # If run_tag or file specified, read runs from JSONL
    target_file = None
    if args.file_path and os.path.exists(args.file_path):
        target_file = args.file_path
    elif args.run_tag:
        candidate = os.path.join(PROJECT_ROOT, "results", "raw", f"{args.run_tag}.jsonl")
        if os.path.exists(candidate):
            target_file = candidate

    if target_file:
        from collections import defaultdict
        path_metrics = defaultdict(lambda: defaultdict(list))
        with open(target_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get("warmup"):
                    continue
                p = record.get("path")
                metrics = record.get("metrics", record)
                cost_res = calculate_run_cost(metrics, pricing=pricing)
                for k, v in cost_res.items():
                    path_metrics[p][k].append(v)

        avg_path_costs = {}
        for p, metric_dict in path_metrics.items():
            avg_path_costs[p] = {k: sum(vals) / max(1, len(vals)) for k, vals in metric_dict.items()}

        print(f"\nMeasured Cost Model from '{target_file}':")
        print(format_cost_table(avg_path_costs))
        return

    # Default baseline analytical table for implemented paths (A, B, C, D)
    sample_workload_metrics = {
        "A": {
            "lambda_invocations": 4,
            "lambda_duration_ms": 600.0,
            "eventbridge_events": 0,
            "step_functions_transitions": 6,
            "dynamodb_wru": 4,
            "dynamodb_rru": 1,
            "sqs_requests": 0,
        },
        "B": {
            "lambda_invocations": 4,
            "lambda_duration_ms": 600.0,
            "eventbridge_events": 4,
            "step_functions_transitions": 0,
            "dynamodb_wru": 5,
            "dynamodb_rru": 2,
            "sqs_requests": 0,
        },
        "C": {
            "lambda_invocations": 4,
            "lambda_duration_ms": 600.0,
            "eventbridge_events": 1,
            "step_functions_transitions": 5,
            "dynamodb_wru": 5,
            "dynamodb_rru": 2,
            "sqs_requests": 0,
        },
        "D": {
            "lambda_invocations": 5,
            "lambda_duration_ms": 650.0,
            "eventbridge_events": 4,
            "step_functions_transitions": 0,
            "dynamodb_wru": 8,
            "dynamodb_rru": 6,
            "sqs_requests": 0,
        },
    }

    results = {p: calculate_run_cost(m, pricing=pricing) for p, m in sample_workload_metrics.items()}
    print("\nAnalytical Baseline Cost Model (Per 1,000 Transactions):")
    print(format_cost_table(results))


if __name__ == "__main__":
    main()
