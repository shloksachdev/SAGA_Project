"""
Purpose: Pure Python dependency DAG compensation scheduler and LIFO ablation (D5, §4 Phase 5).
Phase: Phase 5
Constraint: No boto3, no static workload references (D5).
"""

import heapq
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from common.core.dag import Graph, Node

logger = logging.getLogger(__name__)

STATUS_COMPENSATED = "COMPENSATED"
STATUS_COMPENSATION_FAILED = "COMPENSATION_FAILED"

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_INTERVAL_SEC = 1.0


class VirtualClock:
    """Discrete-event virtual clock for deterministic unit testing without wall-clock sleep."""

    def __init__(self, start_time: float = 0.0):
        self.current_time: float = start_time
        self.events: List[Tuple[float, int, Callable[[], None]]] = []
        self._seq: int = 0

    def now(self) -> float:
        return self.current_time

    def sleep(self, duration: float) -> None:
        self.current_time += duration

    def schedule(self, delay: float, callback: Callable[[], None]) -> None:
        self._seq += 1
        heapq.heappush(self.events, (self.current_time + delay, self._seq, callback))

    def step(self) -> bool:
        if not self.events:
            return False
        event_time, _, cb = heapq.heappop(self.events)
        self.current_time = event_time
        cb()
        return True

    def run_all(self) -> None:
        while self.step():
            pass


def run_parallel(
    graph: Graph,
    exec_fn: Callable[[Node], Any],
    max_workers: int = 8,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    interval_sec: float = DEFAULT_INTERVAL_SEC,
    clock: Optional[VirtualClock] = None,
) -> str:
    """
    Executes compensation nodes in parallel honoring DAG dependencies.
    - Releases dependents as nodes complete.
    - Retries up to max_attempts on failure.
    - If a node exhausts retries, marks it failed, blocks its dependents,
      finishes remaining independent branches, and returns 'COMPENSATION_FAILED'.
    - If all nodes succeed, returns 'COMPENSATED'.
    """
    if not graph.nodes:
        return STATUS_COMPENSATED

    if clock is not None:
        return _run_parallel_virtual(
            graph=graph,
            exec_fn=exec_fn,
            max_workers=max_workers,
            max_attempts=max_attempts,
            interval_sec=interval_sec,
            clock=clock,
        )
    else:
        return _run_parallel_threaded(
            graph=graph,
            exec_fn=exec_fn,
            max_workers=max_workers,
            max_attempts=max_attempts,
            interval_sec=interval_sec,
        )


def _run_parallel_virtual(
    graph: Graph,
    exec_fn: Callable[[Node], Any],
    max_workers: int,
    max_attempts: int,
    interval_sec: float,
    clock: VirtualClock,
) -> str:
    completed: Set[str] = set()
    failed: Set[str] = set()
    in_flight: Set[str] = set()
    attempts: Dict[str, int] = {name: 0 for name in graph.nodes}

    def dispatch_ready():
        # Check blocked nodes whose dependencies failed
        for name in graph.nodes:
            if name not in completed and name not in failed and name not in in_flight:
                if any(dep in failed for dep in graph.dependencies[name]):
                    failed.add(name)

        ready_names = [
            n for n in graph.ready(completed)
            if n not in in_flight and n not in completed and n not in failed
        ]

        for name in ready_names:
            if len(in_flight) >= max_workers:
                break
            in_flight.add(name)
            node = graph.nodes[name]
            _schedule_node_execution(node)

    def _schedule_node_execution(node: Node):
        attempts[node.step] += 1
        cur_attempt = attempts[node.step]

        duration = getattr(node, "duration", 0.0)

        def on_complete():
            success = True
            try:
                res = exec_fn(node)
                if res is False:
                    success = False
            except Exception:
                success = False

            if success:
                in_flight.remove(node.step)
                completed.add(node.step)
                dispatch_ready()
            else:
                if cur_attempt < max_attempts:
                    # Retry after interval
                    clock.schedule(interval_sec, lambda: _schedule_node_execution(node))
                else:
                    in_flight.remove(node.step)
                    failed.add(node.step)
                    dispatch_ready()

        clock.schedule(duration, on_complete)

    # Initial dispatch
    dispatch_ready()
    clock.run_all()

    if failed:
        return STATUS_COMPENSATION_FAILED
    return STATUS_COMPENSATED


def _run_parallel_threaded(
    graph: Graph,
    exec_fn: Callable[[Node], Any],
    max_workers: int,
    max_attempts: int,
    interval_sec: float,
) -> str:
    completed: Set[str] = set()
    failed: Set[str] = set()
    in_flight: Set[str] = set()
    lock = threading.Lock()
    cv = threading.Condition(lock)

    def worker(node: Node):
        for attempt in range(1, max_attempts + 1):
            try:
                exec_fn(node)
                with lock:
                    in_flight.remove(node.step)
                    completed.add(node.step)
                    cv.notify_all()
                return
            except Exception as e:
                logger.warning(
                    f"[scheduler] Node {node.step} attempt {attempt}/{max_attempts} failed: {e}"
                )
                if attempt < max_attempts:
                    time.sleep(interval_sec)
                else:
                    with lock:
                        in_flight.remove(node.step)
                        failed.add(node.step)
                        cv.notify_all()
                    return

    threads: List[threading.Thread] = []

    with lock:
        while True:
            # Check blocked nodes whose dependencies failed
            for name in graph.nodes:
                if name not in completed and name not in failed and name not in in_flight:
                    if any(dep in failed for dep in graph.dependencies[name]):
                        failed.add(name)

            ready_names = [
                n for n in graph.ready(completed)
                if n not in in_flight and n not in completed and n not in failed
            ]

            dispatched_any = False
            for name in ready_names:
                if len(in_flight) >= max_workers:
                    break
                in_flight.add(name)
                dispatched_any = True
                t = threading.Thread(target=worker, args=(graph.nodes[name],), daemon=True)
                threads.append(t)
                t.start()

            if not in_flight:
                # All reachable nodes finished
                break

            cv.wait()

    for t in threads:
        t.join(timeout=1.0)

    if failed:
        return STATUS_COMPENSATION_FAILED
    return STATUS_COMPENSATED


def run_lifo(
    graph: Graph,
    exec_fn: Callable[[Node], Any],
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    interval_sec: float = DEFAULT_INTERVAL_SEC,
    clock: Optional[VirtualClock] = None,
) -> str:
    """
    Executes compensation nodes sequentially in descending seq order.
    Ignores compensateAfter (controlled ablation against parallel DAG).
    """
    if not graph.nodes:
        return STATUS_COMPENSATED

    # Sort descending by sequence number
    nodes = sorted(graph.nodes.values(), key=lambda n: n.seq, reverse=True)

    for node in nodes:
        success = False
        for attempt in range(1, max_attempts + 1):
            if clock is not None:
                duration = getattr(node, "duration", 0.0)
                clock.sleep(duration)
                try:
                    res = exec_fn(node)
                    if res is not False:
                        success = True
                        break
                except Exception:
                    pass
                if attempt < max_attempts:
                    clock.sleep(interval_sec)
            else:
                try:
                    exec_fn(node)
                    success = True
                    break
                except Exception as e:
                    logger.warning(
                        f"[lifo] Node {node.step} attempt {attempt}/{max_attempts} failed: {e}"
                    )
                    if attempt < max_attempts:
                        time.sleep(interval_sec)

        if not success:
            return STATUS_COMPENSATION_FAILED

    return STATUS_COMPENSATED
