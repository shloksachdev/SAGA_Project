"""
Purpose: Acceptance tests for DAG generation in discrete-event simulation (SPEC §4 Phase 9).
Phase: Phase 9
"""

import random
import pytest

from sim.dags import (
    chain,
    diamond,
    independent,
    layered_random,
    order_workload,
    trainticket_workload,
    wide_fan,
    wide_workload,
)


def test_chain_dag():
    g = chain(depth=5, duration=50.0)
    assert len(g.nodes) == 5
    layers = g.layers()
    assert len(layers) == 5
    # Compensation execution order: Step5 -> Step4 -> Step3 -> Step2 -> Step1
    assert layers == [["Step5"], ["Step4"], ["Step3"], ["Step2"], ["Step1"]]


def test_independent_dag():
    g = independent(n=6, duration=40.0)
    assert len(g.nodes) == 6
    layers = g.layers()
    assert len(layers) == 1
    # All 6 nodes are in Layer 0
    assert len(layers[0]) == 6


def test_wide_fan_dag():
    g = wide_fan(width=4, root_duration=100.0, leaf_duration=50.0)
    assert len(g.nodes) == 5
    layers = g.layers()
    assert len(layers) == 2
    # Layer 0: all 4 leaves; Layer 1: Root
    assert sorted(layers[0]) == ["Leaf1", "Leaf2", "Leaf3", "Leaf4"]
    assert layers[1] == ["Root"]


def test_diamond_dag():
    g = diamond(width=3, duration=30.0)
    assert len(g.nodes) == 5
    layers = g.layers()
    assert len(layers) == 3
    assert layers[0] == ["Sink"]
    assert sorted(layers[1]) == ["Mid1", "Mid2", "Mid3"]
    assert layers[2] == ["Source"]


def test_layered_random_dag():
    rng = random.Random(1337)
    g = layered_random(depth=4, width=3, edge_density=0.4, rng=rng)
    assert len(g.nodes) == 12
    layers = g.layers()
    assert len(layers) >= 4


def test_workload_shapes():
    # Order
    g_ord = order_workload()
    assert len(g_ord.nodes) == 3
    layers_ord = g_ord.layers()
    assert sorted(layers_ord[0]) == ["Inventory", "Payment"]
    assert layers_ord[1] == ["Order"]

    # TrainTicket
    g_tt = trainticket_workload()
    assert len(g_tt.nodes) == 3
    layers_tt = g_tt.layers()
    assert layers_tt == [["Inventory"], ["Payment"], ["Order"]]

    # Wide-k
    g_w4 = wide_workload(4)
    assert len(g_w4.nodes) == 5
    layers_w4 = g_w4.layers()
    assert sorted(layers_w4[0]) == ["Step1", "Step2", "Step3", "Step4"]
    assert layers_w4[1] == ["Order"]
