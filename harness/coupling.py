"""
Purpose: Architectural coupling metric derivation per path (§3.5, Task 5).
Phase: Phase 8
"""

import ast
import os
import sys
from typing import Any, Dict, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common.aws import get_boto3_client
from common.workloads import get_workload
from paths.a.build_asl import build_asl as build_asl_a
from paths.c.build_asl import build_asl as build_asl_c

BANNED_SERVICES = {"Order", "Payment", "Inventory", "Notification", "Step1", "Step2", "Step3", "Step4"}


def count_asl_lambda_refs(asl_def: Dict[str, Any]) -> int:
    """Counts distinct Lambda ARN references in a Step Functions ASL definition."""
    refs = set()
    states = asl_def.get("States", {})
    for state in states.values():
        res = state.get("Resource", "")
        if "arn:aws:lambda:" in res:
            refs.add(res)
    return len(refs)


def count_orchestrator_static_refs() -> int:
    """
    Statically analyzes Path D dynamic coordination modules using AST.
    Returns the count of hardcoded service name references (must be 0 per D5).
    """
    target_files = [
        os.path.join(PROJECT_ROOT, "common", "orchestrator.py"),
        os.path.join(PROJECT_ROOT, "common", "election.py"),
        os.path.join(PROJECT_ROOT, "common", "lease.py"),
        os.path.join(PROJECT_ROOT, "common", "core", "dag.py"),
        os.path.join(PROJECT_ROOT, "common", "core", "scheduler.py"),
    ]
    violations = 0
    for path in target_files:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant):
                val = node.value
                if isinstance(val, str) and val in BANNED_SERVICES:
                    violations += 1
            elif isinstance(node, ast.Name) and node.id in BANNED_SERVICES:
                violations += 1
    return violations


def evaluate_coupling(workload_name: str = "order") -> Dict[str, Dict[str, Any]]:
    """Evaluates coupling metrics across Paths A, B, C, and D."""
    workload = get_workload(workload_name)
    results = {}

    # 1. Path A: Pure Orchestration
    asl_a = build_asl_a(workload)
    asl_refs_a = count_asl_lambda_refs(asl_a)
    results["A"] = {
        "asl_refs": asl_refs_a,
        "eb_forward_rules": 0,
        "eb_comp_rules": 0,
        "eb_total_rules": 0,
        "orchestrator_static_refs": "N/A",
        "total_coupling": asl_refs_a,
        "notes": f"{asl_refs_a} distinct Lambda ARNs tightly bound in ASL",
    }

    # 2. Path B: Pure Choreography
    # Order forward: 4 rules. Reverse comp: 3 rules.
    num_steps = len(workload.steps)
    b_fwd_rules = num_steps
    b_comp_rules = max(0, num_steps - 1)
    b_total = b_fwd_rules + b_comp_rules
    results["B"] = {
        "asl_refs": 0,
        "eb_forward_rules": b_fwd_rules,
        "eb_comp_rules": b_comp_rules,
        "eb_total_rules": b_total,
        "orchestrator_static_refs": "N/A",
        "total_coupling": b_total,
        "notes": f"{b_fwd_rules} forward rules + {b_comp_rules} reverse compensation rules on saga-bus-b",
    }

    # 3. Path C: Static Hybrid
    asl_c = build_asl_c(workload)
    asl_refs_c = count_asl_lambda_refs(asl_c)
    c_edge_rules = 1  # OrderCoreCompleted -> Notification
    c_total = asl_refs_c + c_edge_rules
    results["C"] = {
        "asl_refs": asl_refs_c,
        "eb_forward_rules": c_edge_rules,
        "eb_comp_rules": 0,
        "eb_total_rules": c_edge_rules,
        "orchestrator_static_refs": "N/A",
        "total_coupling": c_total,
        "notes": f"{asl_refs_c} core Lambda refs in ASL + {c_edge_rules} edge rule on saga-bus-c",
    }

    # 4. Path D: Dynamic Coordination
    d_fwd_rules = num_steps
    d_election_rules = 1
    d_static_refs = count_orchestrator_static_refs()
    results["D"] = {
        "asl_refs": 0,
        "eb_forward_rules": d_fwd_rules,
        "eb_comp_rules": d_election_rules,
        "eb_total_rules": d_fwd_rules + d_election_rules,
        "orchestrator_static_refs": d_static_refs,
        "total_coupling": d_fwd_rules + d_election_rules,
        "notes": (
            f"{d_fwd_rules} steady-state forward rules + {d_election_rules} fan-in election rule; "
            f"{d_static_refs} orchestrator static service references (D5)"
        ),
    }

    return results


def format_coupling_table(coupling_data: Dict[str, Dict[str, Any]]) -> str:
    lines = [
        "| Path | Architecture Type | ASL Lambda Refs | Forward EB Rules | Reverse/Comp EB Rules | Orchestrator Static Refs | Total Coupling Metric | Notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    arch_map = {
        "A": "Pure Orchestration",
        "B": "Pure Choreography",
        "C": "Static Hybrid",
        "D": "Dynamic Orchestration",
    }
    for path, data in sorted(coupling_data.items()):
        lines.append(
            f"| **{path}** | {arch_map.get(path, path)} | {data['asl_refs']} | "
            f"{data['eb_forward_rules']} | {data['eb_comp_rules']} | "
            f"**{data['orchestrator_static_refs']}** | **{data['total_coupling']}** | {data['notes']} |"
        )
    return "\n".join(lines)


def main():
    coupling = evaluate_coupling("order")
    print("\nArchitectural Coupling Report (Workload: order):")
    print(format_coupling_table(coupling))


if __name__ == "__main__":
    main()
