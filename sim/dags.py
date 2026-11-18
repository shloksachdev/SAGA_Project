"""
Purpose: DAG generators for discrete-event saga compensation simulation (SPEC §4 Phase 9).
Phase: Phase 9
Constraint: Uses common/core/dag.py for dependency semantics so there is a single definition.
"""

import random
from typing import Any, Dict, List, Optional
from common.core.dag import Graph, build_compensation_graph


def chain(depth: int, duration: float = 100.0) -> Graph:
    """
    Generates a sequential chain of compensation steps.
    In compensation, Step_i compensates strictly after Step_{i+1}.
    Step_{depth} has no dependencies and starts first.
    """
    records: List[Dict[str, Any]] = []
    for i in range(1, depth + 1):
        step_name = f"Step{i}"
        comp_after = [f"Step{i+1}"] if i < depth else []
        records.append({
            "step": step_name,
            "status": "COMPLETED",
            "seq": i,
            "compensatorFn": f"fn_{step_name}",
            "compensateAction": f"comp_{step_name}",
            "compensateAfter": comp_after,
            "duration": float(duration),
        })
    return build_compensation_graph(records)


def independent(n: int, duration: float = 100.0) -> Graph:
    """
    Generates n completely independent compensation steps.
    Every step has compensateAfter = [], enabling maximal parallel compaction.
    """
    records: List[Dict[str, Any]] = []
    for i in range(1, n + 1):
        step_name = f"Node{i}"
        records.append({
            "step": step_name,
            "status": "COMPLETED",
            "seq": i,
            "compensatorFn": f"fn_{step_name}",
            "compensateAction": f"comp_{step_name}",
            "compensateAfter": [],
            "duration": float(duration),
        })
    return build_compensation_graph(records)


def wide_fan(width: int, root_duration: float = 100.0, leaf_duration: float = 100.0) -> Graph:
    """
    Generates a wide-fan DAG with 1 root step and `width` independent leaf steps.
    Root step (seq=1) has compensateAfter = ["*"] (waits for all leaves).
    Leaves (seq=2..width+1) have compensateAfter = [] (run in parallel).
    """
    records: List[Dict[str, Any]] = [
        {
            "step": "Root",
            "status": "COMPLETED",
            "seq": 1,
            "compensatorFn": "fn_Root",
            "compensateAction": "comp_Root",
            "compensateAfter": ["*"],
            "duration": float(root_duration),
        }
    ]
    for i in range(1, width + 1):
        step_name = f"Leaf{i}"
        records.append({
            "step": step_name,
            "status": "COMPLETED",
            "seq": i + 1,
            "compensatorFn": f"fn_{step_name}",
            "compensateAction": f"comp_{step_name}",
            "compensateAfter": [],
            "duration": float(leaf_duration),
        })
    return build_compensation_graph(records)


def diamond(width: int = 2, duration: float = 100.0) -> Graph:
    """
    Generates a diamond DAG:
    - Sink: starts first (compensateAfter = [])
    - Mid1..MidW: parallel layer, start after Sink (compensateAfter = ["Sink"])
    - Source: completes last, starts after all Mid steps (compensateAfter = [Mid1..MidW])
    """
    records: List[Dict[str, Any]] = [
        {
            "step": "Sink",
            "status": "COMPLETED",
            "seq": width + 2,
            "compensatorFn": "fn_Sink",
            "compensateAction": "comp_Sink",
            "compensateAfter": [],
            "duration": float(duration),
        }
    ]
    mid_names = []
    for i in range(1, width + 1):
        name = f"Mid{i}"
        mid_names.append(name)
        records.append({
            "step": name,
            "status": "COMPLETED",
            "seq": i + 1,
            "compensatorFn": f"fn_{name}",
            "compensateAction": f"comp_{name}",
            "compensateAfter": ["Sink"],
            "duration": float(duration),
        })
    records.append({
        "step": "Source",
        "status": "COMPLETED",
        "seq": 1,
        "compensatorFn": "fn_Source",
        "compensateAction": "comp_Source",
        "compensateAfter": mid_names,
        "duration": float(duration),
    })
    return build_compensation_graph(records)


def layered_random(
    depth: int,
    width: int,
    edge_density: float = 0.5,
    rng: Optional[random.Random] = None,
    duration: float = 100.0,
) -> Graph:
    """
    Generates a layered random acyclic DAG.
    Depth layers: layer 0 runs first, subsequent layers depend on prior layers
    with probability edge_density.
    """
    if rng is None:
        rng = random.Random(42)

    layers: List[List[str]] = []
    records: List[Dict[str, Any]] = []
    seq_counter = 1

    for d in range(depth):
        layer_nodes = []
        for w in range(width):
            name = f"L{d}_N{w}"
            layer_nodes.append(name)
            # Pick dependencies from the immediately previous layer (or earlier)
            deps = []
            if d > 0:
                prev_layer = layers[d - 1]
                for p in prev_layer:
                    if rng.random() < edge_density:
                        deps.append(p)
                # Ensure at least 1 dependency if edge_density > 0 and d > 0
                if not deps and prev_layer:
                    deps.append(rng.choice(prev_layer))

            records.append({
                "step": name,
                "status": "COMPLETED",
                "seq": seq_counter,
                "compensatorFn": f"fn_{name}",
                "compensateAction": f"comp_{name}",
                "compensateAfter": deps,
                "duration": float(duration),
            })
            seq_counter += 1
        layers.append(layer_nodes)

    return build_compensation_graph(records)


# =============================================================================
# Real System Workloads (Order, TrainTicket, Wide-k)
# =============================================================================

def order_workload(durations: Optional[Dict[str, float]] = None) -> Graph:
    """
    Order saga shape:
    - Order: seq=1, compensateAfter=["*"]
    - Payment: seq=2, compensateAfter=[]
    - Inventory: seq=3, compensateAfter=[]
    """
    d = durations or {"Order": 100.0, "Payment": 100.0, "Inventory": 100.0}
    records = [
        {
            "step": "Order",
            "status": "COMPLETED",
            "seq": 1,
            "compensatorFn": "Order",
            "compensateAction": "cancel",
            "compensateAfter": ["*"],
            "duration": float(d.get("Order", 100.0)),
        },
        {
            "step": "Payment",
            "status": "COMPLETED",
            "seq": 2,
            "compensatorFn": "Payment",
            "compensateAction": "compensate",
            "compensateAfter": [],
            "duration": float(d.get("Payment", 100.0)),
        },
        {
            "step": "Inventory",
            "status": "COMPLETED",
            "seq": 3,
            "compensatorFn": "Inventory",
            "compensateAction": "release",
            "compensateAfter": [],
            "duration": float(d.get("Inventory", 100.0)),
        },
    ]
    return build_compensation_graph(records)


def trainticket_workload(durations: Optional[Dict[str, float]] = None) -> Graph:
    """
    TrainTicket saga shape:
    - Order: seq=1, compensateAfter=["*"]
    - Payment: seq=2, compensateAfter=["Inventory"] (seat released before refund)
    - Inventory: seq=3, compensateAfter=[]
    """
    d = durations or {"Order": 100.0, "Payment": 100.0, "Inventory": 100.0}
    records = [
        {
            "step": "Order",
            "status": "COMPLETED",
            "seq": 1,
            "compensatorFn": "Order",
            "compensateAction": "cancel",
            "compensateAfter": ["*"],
            "duration": float(d.get("Order", 100.0)),
        },
        {
            "step": "Payment",
            "status": "COMPLETED",
            "seq": 2,
            "compensatorFn": "Payment",
            "compensateAction": "compensate",
            "compensateAfter": ["Inventory"],
            "duration": float(d.get("Payment", 100.0)),
        },
        {
            "step": "Inventory",
            "status": "COMPLETED",
            "seq": 3,
            "compensatorFn": "Inventory",
            "compensateAction": "release",
            "compensateAfter": [],
            "duration": float(d.get("Inventory", 100.0)),
        },
    ]
    return build_compensation_graph(records)


def wide_workload(k: int, durations: Optional[Dict[str, float]] = None) -> Graph:
    """
    Wide-k workload shape:
    - Order: seq=1, compensateAfter=["*"]
    - Step1..Stepk: seq=2..k+1, compensateAfter=[]
    """
    d = durations or {}
    records = [
        {
            "step": "Order",
            "status": "COMPLETED",
            "seq": 1,
            "compensatorFn": "Order",
            "compensateAction": "cancel",
            "compensateAfter": ["*"],
            "duration": float(d.get("Order", 100.0)),
        }
    ]
    for i in range(1, k + 1):
        name = f"Step{i}"
        records.append({
            "step": name,
            "status": "COMPLETED",
            "seq": i + 1,
            "compensatorFn": name,
            "compensateAction": "compensate",
            "compensateAfter": [],
            "duration": float(d.get(name, 100.0)),
        })
    return build_compensation_graph(records)
