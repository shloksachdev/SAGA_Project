"""
Purpose: Determinism acceptance tests asserting identical CSV hashes across identical seeds (SPEC §4 Phase 9).
Phase: Phase 9
"""

import hashlib
import os
import tempfile
import pytest

from sim.run import (
    run_crash_sweep,
    run_election_sweep,
    run_makespan_sweep,
)


def hash_file(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def test_simulation_determinism():
    seed = 12345
    with tempfile.TemporaryDirectory() as dir1, tempfile.TemporaryDirectory() as dir2:
        # Run sweep 1
        e1 = run_election_sweep(dir1, seed=seed)
        m1 = run_makespan_sweep(dir1, seed=seed)
        c1 = run_crash_sweep(dir1, seed=seed)

        # Run sweep 2
        e2 = run_election_sweep(dir2, seed=seed)
        m2 = run_makespan_sweep(dir2, seed=seed)
        c2 = run_crash_sweep(dir2, seed=seed)

        # Assert identical SHA-256 hashes
        assert hash_file(e1) == hash_file(e2), "Election sweep CSVs differ across identical seeds"
        assert hash_file(m1) == hash_file(m2), "Makespan sweep CSVs differ across identical seeds"
        assert hash_file(c1) == hash_file(c2), "Crash sweep CSVs differ across identical seeds"
