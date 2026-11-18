"""
Purpose: Pure Python directed acyclic graph (DAG) builder for compensation plans (D5).
Phase: Phase 5
Constraint: No boto3, no static workload references (D5).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


class CyclicDependency(Exception):
    """Raised when a cycle is detected in the compensation graph."""
    pass


@dataclass
class Node:
    step: str
    compensator_fn: Optional[str]
    compensate_action: Optional[str]
    seq: int = 0
    status: str = "COMPLETED"
    compensate_after: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def compensatorFn(self) -> Optional[str]:
        return self.compensator_fn

    @property
    def compensateAction(self) -> Optional[str]:
        return self.compensate_action


class Graph:
    def __init__(
        self,
        nodes: Dict[str, Node],
        dependencies: Dict[str, Set[str]],
        dependents: Dict[str, Set[str]],
    ):
        self.nodes = nodes
        self.dependencies = dependencies
        self.dependents = dependents

    def layers(self) -> List[List[str]]:
        """
        Computes topological layers of the graph.
        Layer 0 contains all nodes with 0 unsatisfied dependencies.
        Subsequent layers contain nodes released by prior layers.
        """
        if not self.nodes:
            return []
        in_degree = {k: len(self.dependencies.get(k, set())) for k in self.nodes}
        current_layer = [k for k, deg in in_degree.items() if deg == 0]
        all_layers: List[List[str]] = []
        while current_layer:
            current_layer.sort(key=lambda x: (self.nodes[x].seq, x))
            all_layers.append(current_layer)
            next_layer: List[str] = []
            for n in current_layer:
                for dep in self.dependents.get(n, set()):
                    in_degree[dep] -= 1
                    if in_degree[dep] == 0:
                        next_layer.append(dep)
            current_layer = next_layer
        return all_layers

    def ready(self, done_set: Set[str]) -> List[str]:
        """
        Returns list of nodes whose dependencies are all in done_set,
        and which are not themselves in done_set.
        """
        candidates: List[str] = []
        for name, deps in self.dependencies.items():
            if name not in done_set and deps.issubset(done_set):
                candidates.append(name)
        candidates.sort(key=lambda x: (self.nodes[x].seq, x))
        return candidates


def build_compensation_graph(
    step_records: List[Dict[str, Any]],
    failed_step: Optional[str] = None,
) -> Graph:
    """
    Builds a compensation dependency DAG from step records.
    - Nodes: steps with status COMPLETED or COMPENSATING, plus the failed
      step only if its compensateOnFailure is True.
    - Edges: from each node's compensateAfter (resolving '*' to every other node).
    - Dependencies on steps already COMPENSATED or not in the node set are satisfied.
    - Raises CyclicDependency on cycles.
    """
    active_nodes: Dict[str, Node] = {}
    records_by_name: Dict[str, Dict[str, Any]] = {}

    for rec in step_records:
        name = rec.get("step")
        if not name:
            continue
        records_by_name[name] = rec
        status = rec.get("status")

        # Check node eligibility
        is_completed_or_compensating = status in ("COMPLETED", "COMPENSATING")
        is_failed_step = (name == failed_step) or (status == "FAILED")
        compensate_on_failure = bool(rec.get("compensateOnFailure", False))

        if is_completed_or_compensating or (is_failed_step and compensate_on_failure):
            raw_after = rec.get("compensateAfter", [])
            if isinstance(raw_after, str):
                raw_after = [raw_after]
            node = Node(
                step=name,
                compensator_fn=rec.get("compensatorFn"),
                compensate_action=rec.get("compensateAction"),
                seq=int(rec.get("seq", 0)),
                status=status or "COMPLETED",
                compensate_after=list(raw_after),
                raw=rec,
            )
            active_nodes[name] = node

    # Build dependency maps
    dependencies: Dict[str, Set[str]] = {name: set() for name in active_nodes}
    dependents: Dict[str, Set[str]] = {name: set() for name in active_nodes}

    for name, node in active_nodes.items():
        if "*" in node.compensate_after:
            # Resolves '*' to every other active node
            for other_name in active_nodes:
                if other_name != name:
                    dependencies[name].add(other_name)
                    dependents[other_name].add(name)
        else:
            for dep_name in node.compensate_after:
                if dep_name in active_nodes and dep_name != name:
                    dependencies[name].add(dep_name)
                    dependents[dep_name].add(name)
                # If dep_name is already COMPENSATED or not in active_nodes, it is satisfied

    # Cycle detection via Kahn's algorithm
    in_degree = {k: len(dependencies[k]) for k in active_nodes}
    queue = [k for k, deg in in_degree.items() if deg == 0]
    visited_count = 0

    while queue:
        curr = queue.pop(0)
        visited_count += 1
        for dep in dependents.get(curr, set()):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)

    if visited_count < len(active_nodes):
        raise CyclicDependency("Cycle detected in compensation dependency graph")

    return Graph(nodes=active_nodes, dependencies=dependencies, dependents=dependents)
