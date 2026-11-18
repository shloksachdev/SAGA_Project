"""
Purpose: SimPy discrete-event simulation model for distributed saga election & compensation (SPEC §4 Phase 9).
Phase: Phase 9
Features:
- N participants racing conditional-write DynamoDB lease
- Latency distributions: constant, lognormal, heavy-tailed
- Lease TTL and periodic heartbeat
- Leader crash probability p and watcher lease-expiry takeover
- Dynamic DAG parallel scheduler vs LIFO sequential ablation
- Shared service resource pool with Poisson arrival rate λ
"""

import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
import simpy

from common.core.dag import Graph, Node


# =============================================================================
# Latency Distributions
# =============================================================================

class LatencyDistribution:
    """Base class for sampling network/detection arrival latencies in ms."""
    def sample(self, rng: random.Random) -> float:
        raise NotImplementedError


class ConstantDistribution(LatencyDistribution):
    def __init__(self, val_ms: float = 15.0):
        self.val_ms = float(val_ms)

    def sample(self, rng: random.Random) -> float:
        return self.val_ms


class LognormalDistribution(LatencyDistribution):
    def __init__(self, median_ms: float = 15.0, sigma: float = 0.5):
        self.mu = math.log(max(1.0, median_ms))
        self.sigma = float(sigma)

    def sample(self, rng: random.Random) -> float:
        return max(1.0, rng.lognormvariate(self.mu, self.sigma))


class HeavyTailedDistribution(LatencyDistribution):
    def __init__(self, min_ms: float = 10.0, alpha: float = 1.5):
        self.min_ms = float(min_ms)
        self.alpha = float(alpha)

    def sample(self, rng: random.Random) -> float:
        u = max(1e-6, rng.random())
        return max(self.min_ms, self.min_ms / (u ** (1.0 / self.alpha)))


def get_distribution(name: str, **kwargs) -> LatencyDistribution:
    n = name.lower().replace("-", "_")
    if n == "constant":
        return ConstantDistribution(val_ms=kwargs.get("val_ms", 15.0))
    elif n == "lognormal":
        return LognormalDistribution(
            median_ms=kwargs.get("median_ms", 15.0),
            sigma=kwargs.get("sigma", 0.5),
        )
    elif n in ("heavy_tailed", "heavytailed", "pareto"):
        return HeavyTailedDistribution(
            min_ms=kwargs.get("min_ms", 10.0),
            alpha=kwargs.get("alpha", 1.5),
        )
    else:
        raise ValueError(f"Unknown latency distribution: {name}")


# =============================================================================
# Lease State Table
# =============================================================================

@dataclass
class LeaseState:
    leader_id: Optional[str] = None
    acquired_at: float = -1.0
    expires_at: float = -1.0

    def is_valid(self, now: float) -> bool:
        return self.leader_id is not None and self.expires_at > now

    def try_acquire(self, participant_id: str, now: float, ttl_ms: float) -> bool:
        if not self.is_valid(now):
            self.leader_id = participant_id
            self.acquired_at = now
            self.expires_at = now + ttl_ms
            return True
        return False

    def heartbeat(self, participant_id: str, now: float, ttl_ms: float) -> bool:
        if self.leader_id == participant_id:
            self.expires_at = now + ttl_ms
            return True
        return False

    def vacate(self, participant_id: str):
        if self.leader_id == participant_id:
            self.leader_id = None
            self.expires_at = -1.0


# =============================================================================
# Simulation Result
# =============================================================================

@dataclass
class SimResult:
    saga_id: str
    comp_mode: str
    n_participants: int
    distribution: str
    crash_p: float
    lambda_rate: float
    election_latency_ms: float
    re_elections: int
    compensation_makespan_ms: float
    total_recovery_ms: float
    completed: bool
    step_durations: Dict[str, float] = field(default_factory=dict)


# =============================================================================
# Discrete-Event Saga Runner
# =============================================================================

class SagaSimulation:
    def __init__(
        self,
        env: simpy.Environment,
        graph: Graph,
        n_participants: int = 4,
        comp_mode: str = "parallel",
        dist: Optional[LatencyDistribution] = None,
        crash_p: float = 0.0,
        ttl_ms: float = 3000.0,
        heartbeat_ms: float = 1000.0,
        poll_interval_ms: float = 500.0,
        service_pools: Optional[Dict[str, simpy.Resource]] = None,
        rng: Optional[random.Random] = None,
        saga_id: str = "sim-saga",
        lambda_rate: float = 0.0,
    ):
        self.env = env
        self.graph = graph
        self.n_participants = n_participants
        self.comp_mode = comp_mode.lower()
        self.dist = dist or ConstantDistribution(15.0)
        self.crash_p = float(crash_p)
        self.ttl_ms = float(ttl_ms)
        self.heartbeat_ms = float(heartbeat_ms)
        self.poll_interval_ms = float(poll_interval_ms)
        self.service_pools = service_pools or {}
        self.rng = rng or random.Random(42)
        self.saga_id = saga_id
        self.lambda_rate = lambda_rate

        self.lease = LeaseState()
        self.completed_steps: Set[str] = set()
        self.in_flight_steps: Set[str] = set()
        self.active_workers: List[simpy.Process] = []

        # Metrics
        self.start_time: float = self.env.now
        self.first_election_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self.re_elections: int = 0
        self.completed: bool = False

        # Coordination events
        self.saga_done_event = env.event()
        self.step_event = env.event()

    def run(self):
        """Starts all participant processes."""
        for i in range(self.n_participants):
            pid = f"participant-{i+1}"
            self.env.process(self._participant_process(pid))
        yield self.saga_done_event

    def _participant_process(self, pid: str):
        # 1. Initial arrival delay drawn from distribution
        arrival_delay = self.dist.sample(self.rng)
        yield self.env.timeout(arrival_delay)

        while not self.saga_done_event.triggered:
            # Check if saga is finished
            if len(self.completed_steps) >= len(self.graph.nodes):
                if not self.saga_done_event.triggered:
                    self.end_time = self.env.now
                    self.completed = True
                    self.saga_done_event.succeed()
                return

            now = self.env.now
            # Attempt lease acquisition if unowned or expired
            if not self.lease.is_valid(now):
                won = self.lease.try_acquire(pid, now, self.ttl_ms)
                if won:
                    if self.first_election_time is None:
                        self.first_election_time = now
                    else:
                        self.re_elections += 1

                    crashed = yield self.env.process(self._leader_lifecycle(pid))
                    if crashed:
                        # Leader crashed permanently
                        return
                    else:
                        # Normal completion
                        return

            # Watcher branch: wait until lease expires or saga completes
            wait_time = max(10.0, self.lease.expires_at - self.env.now)
            jitter = self.rng.uniform(10.0, self.poll_interval_ms)
            yield simpy.events.AnyOf(
                self.env,
                [self.saga_done_event, self.env.timeout(wait_time + jitter)]
            )

    def _leader_lifecycle(self, pid: str):
        # Decide if this leader crashes mid-rollback
        will_crash = (self.rng.random() < self.crash_p)
        total_work = sum(float(n.raw.get("duration", 100.0)) for n in self.graph.nodes.values())
        max_crash_delay = max(20.0, total_work * 0.4)
        crash_delay = self.rng.uniform(10.0, max_crash_delay) if will_crash else 0.0

        heartbeat_proc = self.env.process(self._heartbeat_process(pid))
        execution_proc = self.env.process(self._execution_process(pid))

        if will_crash:
            # Leader dies after crash_delay if execution has not finished
            results = yield simpy.events.AnyOf(
                self.env,
                [execution_proc, self.env.timeout(crash_delay)]
            )
            if execution_proc not in results:
                # Crashed! Stop heartbeats, interrupt running workers
                heartbeat_proc.interrupt("crash")
                execution_proc.interrupt("crash")
                for w in self.active_workers:
                    if w.is_alive:
                        w.interrupt("crash")
                self.active_workers.clear()
                self.in_flight_steps.clear()
                # Do NOT vacate lease; let it expire naturally
                return True

        # Successful execution
        yield execution_proc
        heartbeat_proc.interrupt("done")
        self.lease.vacate(pid)
        return False

    def _heartbeat_process(self, pid: str):
        try:
            while True:
                yield self.env.timeout(self.heartbeat_ms)
                self.lease.heartbeat(pid, self.env.now, self.ttl_ms)
        except simpy.Interrupt:
            pass

    def _execution_process(self, pid: str):
        try:
            if self.comp_mode == "parallel":
                yield self.env.process(self._run_parallel_dag())
            else:
                yield self.env.process(self._run_lifo_sequential())

            if len(self.completed_steps) >= len(self.graph.nodes):
                if not self.saga_done_event.triggered:
                    self.end_time = self.env.now
                    self.completed = True
                    self.saga_done_event.succeed()
        except simpy.Interrupt:
            pass

    def _run_parallel_dag(self):
        """Dispatches ready nodes concurrently as dependencies are satisfied."""
        def node_worker(node: Node):
            duration = float(node.raw.get("duration", 100.0))
            service_name = node.compensator_fn or node.step
            try:
                if service_name in self.service_pools:
                    res = self.service_pools[service_name]
                    with res.request() as req:
                        yield req
                        yield self.env.timeout(duration)
                else:
                    yield self.env.timeout(duration)

                if node.step in self.in_flight_steps:
                    self.in_flight_steps.remove(node.step)
                self.completed_steps.add(node.step)

                # Signal progress
                if not self.step_event.triggered:
                    self.step_event.succeed()
            except simpy.Interrupt:
                if node.step in self.in_flight_steps:
                    self.in_flight_steps.remove(node.step)

        while len(self.completed_steps) < len(self.graph.nodes):
            ready_nodes = self.graph.ready(self.completed_steps)
            for step_name in ready_nodes:
                if step_name not in self.in_flight_steps:
                    self.in_flight_steps.add(step_name)
                    node = self.graph.nodes[step_name]
                    proc = self.env.process(node_worker(node))
                    self.active_workers.append(proc)

            if len(self.completed_steps) >= len(self.graph.nodes):
                break

            self.step_event = self.env.event()
            yield self.step_event

    def _run_lifo_sequential(self):
        """Executes nodes strictly sequentially in descending seq order."""
        nodes = sorted(self.graph.nodes.values(), key=lambda n: n.seq, reverse=True)
        for node in nodes:
            if node.step in self.completed_steps:
                continue

            duration = float(node.raw.get("duration", 100.0))
            service_name = node.compensator_fn or node.step
            try:
                if service_name in self.service_pools:
                    res = self.service_pools[service_name]
                    with res.request() as req:
                        yield req
                        yield self.env.timeout(duration)
                else:
                    yield self.env.timeout(duration)

                self.completed_steps.add(node.step)
            except simpy.Interrupt:
                break

    def get_result(self) -> SimResult:
        first_elect = self.first_election_time or self.start_time
        end = self.end_time or self.env.now
        election_latency = first_elect - self.start_time
        comp_makespan = end - first_elect
        total_recovery = end - self.start_time

        return SimResult(
            saga_id=self.saga_id,
            comp_mode=self.comp_mode,
            n_participants=self.n_participants,
            distribution=self.dist.__class__.__name__.replace("Distribution", "").lower(),
            crash_p=self.crash_p,
            lambda_rate=self.lambda_rate,
            election_latency_ms=election_latency,
            re_elections=self.re_elections,
            compensation_makespan_ms=comp_makespan,
            total_recovery_ms=total_recovery,
            completed=self.completed,
        )


# =============================================================================
# Helper entrypoints
# =============================================================================

def simulate_saga(
    graph: Graph,
    n_participants: int = 4,
    comp_mode: str = "parallel",
    distribution: str = "constant",
    dist_kwargs: Optional[Dict[str, Any]] = None,
    crash_p: float = 0.0,
    ttl_ms: float = 3000.0,
    heartbeat_ms: float = 1000.0,
    poll_interval_ms: float = 500.0,
    seed: int = 42,
    service_pools_capacity: Optional[int] = None,
) -> SimResult:
    """Convenience function to run a single saga simulation."""
    env = simpy.Environment()
    rng = random.Random(seed)
    dist = get_distribution(distribution, **(dist_kwargs or {}))

    service_pools = None
    if service_pools_capacity:
        unique_services = {n.compensator_fn or n.step for n in graph.nodes.values()}
        service_pools = {s: simpy.Resource(env, capacity=service_pools_capacity) for s in unique_services}

    sim = SagaSimulation(
        env=env,
        graph=graph,
        n_participants=n_participants,
        comp_mode=comp_mode,
        dist=dist,
        crash_p=crash_p,
        ttl_ms=ttl_ms,
        heartbeat_ms=heartbeat_ms,
        poll_interval_ms=poll_interval_ms,
        service_pools=service_pools,
        rng=rng,
    )
    env.process(sim.run())
    env.run()
    return sim.get_result()


def simulate_batch(
    graph_fn: Callable[[], Graph],
    n_sagas: int = 50,
    n_participants: int = 4,
    comp_mode: str = "parallel",
    distribution: str = "constant",
    dist_kwargs: Optional[Dict[str, Any]] = None,
    lambda_rate: float = 5.0,
    service_capacity: int = 4,
    crash_p: float = 0.0,
    seed: int = 42,
) -> List[SimResult]:
    """Runs a batch of sagas arriving at rate lambda (sagas/s) contending for shared service pools."""
    env = simpy.Environment()
    rng = random.Random(seed)
    dist = get_distribution(distribution, **(dist_kwargs or {}))

    sample_g = graph_fn()
    unique_services = {n.compensator_fn or n.step for n in sample_g.nodes.values()}
    service_pools = {s: simpy.Resource(env, capacity=service_capacity) for s in unique_services}

    results: List[SimResult] = []
    sims: List[SagaSimulation] = []

    def batch_generator():
        rate_per_ms = (lambda_rate / 1000.0) if lambda_rate > 0 else 0.0
        for i in range(n_sagas):
            if rate_per_ms > 0 and i > 0:
                inter_arrival = rng.expovariate(rate_per_ms)
                yield env.timeout(inter_arrival)

            g = graph_fn()
            sim = SagaSimulation(
                env=env,
                graph=g,
                n_participants=n_participants,
                comp_mode=comp_mode,
                dist=dist,
                crash_p=crash_p,
                service_pools=service_pools,
                rng=rng,
                saga_id=f"batch-saga-{i+1}",
                lambda_rate=lambda_rate,
            )
            sims.append(sim)
            env.process(sim.run())

    env.process(batch_generator())
    env.run()

    for s in sims:
        results.append(s.get_result())
    return results

