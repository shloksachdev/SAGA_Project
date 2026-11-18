"""
Purpose: Unit tests for compensation DAG builder and scheduler (Phase 5 acceptance).
Phase: Phase 5
"""

from typing import Dict, List, Set
import pytest

from common.core.dag import CyclicDependency, Graph, Node, build_compensation_graph
from common.core.scheduler import (
    STATUS_COMPENSATED,
    STATUS_COMPENSATION_FAILED,
    VirtualClock,
    run_lifo,
    run_parallel,
)


def _make_node_records(specs: List[Dict]) -> List[Dict]:
    """Helper to construct synthetic step records for DAG building."""
    records = []
    for s in specs:
        records.append({
            "step": s["name"],
            "status": s.get("status", "COMPLETED"),
            "seq": s.get("seq", 1),
            "compensateAfter": s.get("after", []),
            "compensatorFn": f"fn_{s['name']}",
            "compensateAction": f"act_{s['name']}",
            "compensateOnFailure": s.get("compensateOnFailure", False),
        })
    return records


def test_chain_dag():
    """Chain: A -> B -> C -> D. Makespan equals the exact sum of durations."""
    clock = VirtualClock()
    durations = {"A": 10.0, "B": 20.0, "C": 30.0, "D": 40.0}

    specs = [
        {"name": "A", "seq": 1, "after": []},
        {"name": "B", "seq": 2, "after": ["A"]},
        {"name": "C", "seq": 3, "after": ["B"]},
        {"name": "D", "seq": 4, "after": ["C"]},
    ]
    graph = build_compensation_graph(_make_node_records(specs))
    assert graph.layers() == [["A"], ["B"], ["C"], ["D"]]

    for name, node in graph.nodes.items():
        node.duration = durations[name]

    dispatched = []
    def exec_fn(node: Node):
        dispatched.append((node.step, clock.now()))
        return True

    status = run_parallel(graph, exec_fn, clock=clock)
    assert status == STATUS_COMPENSATED
    assert clock.now() == sum(durations.values())
    assert [d[0] for d in dispatched] == ["A", "B", "C", "D"]


def test_diamond_dag():
    """Diamond: Root -> (Left, Right) -> Sink."""
    clock = VirtualClock()
    durations = {"Root": 10.0, "Left": 20.0, "Right": 35.0, "Sink": 15.0}

    specs = [
        {"name": "Root", "seq": 1, "after": []},
        {"name": "Left", "seq": 2, "after": ["Root"]},
        {"name": "Right", "seq": 3, "after": ["Root"]},
        {"name": "Sink", "seq": 4, "after": ["Left", "Right"]},
    ]
    graph = build_compensation_graph(_make_node_records(specs))
    assert graph.layers() == [["Root"], ["Left", "Right"], ["Sink"]]

    for name, node in graph.nodes.items():
        node.duration = durations[name]

    dispatched = []
    def exec_fn(node: Node):
        dispatched.append((node.step, clock.now()))
        return True

    status = run_parallel(graph, exec_fn, clock=clock)
    assert status == STATUS_COMPENSATED
    expected_makespan = 10.0 + max(20.0, 35.0) + 15.0
    assert clock.now() == expected_makespan


def test_star_with_wildcard():
    """Star with '*': D depends on ['*'] -> waits on all other nodes (A, B, C)."""
    clock = VirtualClock()
    durations = {"A": 10.0, "B": 25.0, "C": 15.0, "D": 50.0}

    specs = [
        {"name": "A", "seq": 1, "after": []},
        {"name": "B", "seq": 2, "after": []},
        {"name": "C", "seq": 3, "after": []},
        {"name": "D", "seq": 4, "after": ["*"]},
    ]
    graph = build_compensation_graph(_make_node_records(specs))
    assert graph.layers() == [["A", "B", "C"], ["D"]]

    for name, node in graph.nodes.items():
        node.duration = durations[name]

    status = run_parallel(graph, lambda n: True, clock=clock)
    assert status == STATUS_COMPENSATED
    expected_makespan = max(10.0, 25.0, 15.0) + 50.0
    assert clock.now() == expected_makespan


def test_all_independent():
    """All-independent: Makespan equals the maximum node duration."""
    clock = VirtualClock()
    durations = {"A": 12.0, "B": 45.0, "C": 30.0, "D": 20.0}

    specs = [
        {"name": "A", "seq": 1, "after": []},
        {"name": "B", "seq": 2, "after": []},
        {"name": "C", "seq": 3, "after": []},
        {"name": "D", "seq": 4, "after": []},
    ]
    graph = build_compensation_graph(_make_node_records(specs))
    assert graph.layers() == [["A", "B", "C", "D"]]

    for name, node in graph.nodes.items():
        node.duration = durations[name]

    status = run_parallel(graph, lambda n: True, clock=clock)
    assert status == STATUS_COMPENSATED
    assert clock.now() == max(durations.values())


def test_wide_fan():
    """Wide fan: Root -> 5 parallel children -> Sink."""
    clock = VirtualClock()
    durations = {
        "Root": 10.0,
        "C1": 15.0,
        "C2": 20.0,
        "C3": 25.0,
        "C4": 30.0,
        "C5": 35.0,
        "Sink": 10.0,
    }

    specs = [
        {"name": "Root", "seq": 1, "after": []},
        {"name": "C1", "seq": 2, "after": ["Root"]},
        {"name": "C2", "seq": 3, "after": ["Root"]},
        {"name": "C3", "seq": 4, "after": ["Root"]},
        {"name": "C4", "seq": 5, "after": ["Root"]},
        {"name": "C5", "seq": 6, "after": ["Root"]},
        {"name": "Sink", "seq": 7, "after": ["C1", "C2", "C3", "C4", "C5"]},
    ]
    graph = build_compensation_graph(_make_node_records(specs))
    for name, node in graph.nodes.items():
        node.duration = durations[name]

    status = run_parallel(graph, lambda n: True, clock=clock)
    assert status == STATUS_COMPENSATED
    expected_makespan = 10.0 + 35.0 + 10.0
    assert clock.now() == expected_makespan


def test_cycle_detection():
    """Cycle detection raises CyclicDependency."""
    specs = [
        {"name": "A", "seq": 1, "after": ["C"]},
        {"name": "B", "seq": 2, "after": ["A"]},
        {"name": "C", "seq": 3, "after": ["B"]},
    ]
    with pytest.raises(CyclicDependency):
        build_compensation_graph(_make_node_records(specs))


def test_transient_failure_with_retry():
    """Transient failure on attempt 1 succeeds on attempt 2."""
    clock = VirtualClock()
    specs = [{"name": "A", "seq": 1, "after": []}]
    graph = build_compensation_graph(_make_node_records(specs))
    node = graph.nodes["A"]
    node.duration = 10.0

    call_count = 0
    def exec_fn(n: Node):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return False  # Failure on attempt 1
        return True  # Success on attempt 2

    status = run_parallel(graph, exec_fn, max_attempts=3, interval_sec=1.0, clock=clock)
    assert status == STATUS_COMPENSATED
    assert call_count == 2
    # First attempt: 10s. Retry sleep: 1s. Second attempt: 10s. Total = 21s
    assert clock.now() == 21.0


def test_permanent_failure_blocks_dependents_not_siblings():
    """Permanent failure on node blocks its dependents, but independent siblings finish."""
    clock = VirtualClock()
    # A -> B (fails permanently) -> D (blocked)
    # A -> C (sibling, succeeds)
    durations = {"A": 5.0, "B": 10.0, "C": 20.0, "D": 15.0}

    specs = [
        {"name": "A", "seq": 1, "after": []},
        {"name": "B", "seq": 2, "after": ["A"]},
        {"name": "C", "seq": 3, "after": ["A"]},
        {"name": "D", "seq": 4, "after": ["B"]},
    ]
    graph = build_compensation_graph(_make_node_records(specs))
    for name, node in graph.nodes.items():
        node.duration = durations[name]

    dispatched = set()
    def exec_fn(n: Node):
        dispatched.add(n.step)
        if n.step == "B":
            return False
        return True

    status = run_parallel(graph, exec_fn, max_attempts=3, interval_sec=1.0, clock=clock)
    assert status == STATUS_COMPENSATION_FAILED
    assert "A" in dispatched
    assert "B" in dispatched
    assert "C" in dispatched
    assert "D" not in dispatched  # Blocked dependent


def test_resume_with_already_compensated_steps():
    """Steps already COMPENSATED are skipped and their dependents are unblocked."""
    clock = VirtualClock()
    specs = [
        {"name": "A", "seq": 1, "status": "COMPENSATED", "after": []},
        {"name": "B", "seq": 2, "status": "COMPLETED", "after": ["A"]},
        {"name": "C", "seq": 3, "status": "COMPLETED", "after": ["B"]},
    ]
    graph = build_compensation_graph(_make_node_records(specs))
    assert "A" not in graph.nodes
    assert "B" in graph.nodes
    assert "C" in graph.nodes

    # B's dependency on A is already satisfied
    assert graph.dependencies["B"] == set()
    assert graph.dependencies["C"] == {"B"}

    graph.nodes["B"].duration = 15.0
    graph.nodes["C"].duration = 25.0

    dispatched = []
    def exec_fn(n: Node):
        dispatched.append(n.step)
        return True

    status = run_parallel(graph, exec_fn, clock=clock)
    assert status == STATUS_COMPENSATED
    assert dispatched == ["B", "C"]
    assert clock.now() == 40.0


def test_lifo_ablation_sequential():
    """run_lifo executes strictly in descending seq order, ignoring dependencies."""
    clock = VirtualClock()
    durations = {"A": 10.0, "B": 20.0, "C": 30.0, "D": 40.0}

    specs = [
        {"name": "A", "seq": 1, "after": []},
        {"name": "B", "seq": 2, "after": []},
        {"name": "C", "seq": 3, "after": []},
        {"name": "D", "seq": 4, "after": []},
    ]
    graph = build_compensation_graph(_make_node_records(specs))
    for name, node in graph.nodes.items():
        node.duration = durations[name]

    order = []
    def exec_fn(n: Node):
        order.append(n.step)
        return True

    status = run_lifo(graph, exec_fn, clock=clock)
    assert status == STATUS_COMPENSATED
    assert order == ["D", "C", "B", "A"]
    assert clock.now() == sum(durations.values())
