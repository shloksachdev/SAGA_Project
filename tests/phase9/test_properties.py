"""
Purpose: Formal property tests for SimPy discrete-event simulation (SPEC §4 Phase 9).
Phase: Phase 9
"""

import pytest
from sim.dags import chain, independent
from sim.model import simulate_saga


def test_property_1_chain_equivalence():
    """
    Property Test 1:
    With constant latency and a chain DAG, parallel makespan strictly equals LIFO makespan.
    """
    depth = 5
    duration_per_node = 100.0
    g = chain(depth=depth, duration=duration_per_node)

    res_par = simulate_saga(
        graph=g,
        n_participants=4,
        comp_mode="parallel",
        distribution="constant",
        dist_kwargs={"val_ms": 15.0},
        crash_p=0.0,
    )
    res_lifo = simulate_saga(
        graph=g,
        n_participants=4,
        comp_mode="lifo",
        distribution="constant",
        dist_kwargs={"val_ms": 15.0},
        crash_p=0.0,
    )

    expected_makespan = depth * duration_per_node  # 5 * 100 = 500 ms
    assert res_par.compensation_makespan_ms == expected_makespan
    assert res_lifo.compensation_makespan_ms == expected_makespan
    assert res_par.compensation_makespan_ms == res_lifo.compensation_makespan_ms


def test_property_2_independent_speedup():
    """
    Property Test 2:
    With an all-independent DAG of n nodes of equal duration d:
    parallel makespan ≈ d (and total recovery ≈ d + election overhead),
    while LIFO makespan ≈ n · d (and total recovery ≈ n · d + election overhead).
    """
    n = 6
    duration = 100.0
    election_latency = 20.0
    g = independent(n=n, duration=duration)

    res_par = simulate_saga(
        graph=g,
        n_participants=4,
        comp_mode="parallel",
        distribution="constant",
        dist_kwargs={"val_ms": election_latency},
        crash_p=0.0,
    )
    res_lifo = simulate_saga(
        graph=g,
        n_participants=4,
        comp_mode="lifo",
        distribution="constant",
        dist_kwargs={"val_ms": election_latency},
        crash_p=0.0,
    )

    # Parallel: all n run concurrently
    assert res_par.compensation_makespan_ms == duration
    assert res_par.total_recovery_ms == duration + election_latency

    # LIFO: all n run sequentially
    assert res_lifo.compensation_makespan_ms == n * duration
    assert res_lifo.total_recovery_ms == (n * duration) + election_latency
