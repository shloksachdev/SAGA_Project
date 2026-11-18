"""
Purpose: Acceptance tests for leader crash injection and watcher lease-expiry takeover (SPEC §4 Phase 9).
Phase: Phase 9
"""

import pytest
from sim.dags import wide_fan
from sim.model import simulate_saga


def test_leader_crash_and_watcher_takeover():
    """
    Asserts that under leader crash injection (p > 0):
    1. Watchers observe lease expiration.
    2. A new leader is elected (re_elections > 0 for crashing runs).
    3. All DAG nodes are successfully compensated (completed == True).
    """
    g = wide_fan(width=4, root_duration=100.0, leaf_duration=100.0)

    re_election_seen = False
    for seed in range(20):
        res = simulate_saga(
            graph=g,
            n_participants=4,
            comp_mode="parallel",
            distribution="lognormal",
            crash_p=0.4,
            ttl_ms=500.0,
            heartbeat_ms=150.0,
            poll_interval_ms=100.0,
            seed=seed,
        )
        assert res.completed is True, f"Saga did not complete under seed {seed}"
        if res.re_elections > 0:
            re_election_seen = True
            # When leader crashes, total recovery includes lease TTL wait
            assert res.total_recovery_ms > 500.0

    assert re_election_seen, "Expected at least one re-election across 20 trials with crash_p=0.4"
