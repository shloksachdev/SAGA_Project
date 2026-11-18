"""
Purpose: Acceptance tests asserting sweep completes in under 10 minutes (SPEC §4 Phase 9).
Phase: Phase 9
"""

import tempfile
import time
import pytest

from sim.run import (
    run_calibration,
    run_contention_sweep,
    run_crash_sweep,
    run_election_sweep,
    run_makespan_sweep,
)


def test_sweep_runtime_under_ten_minutes():
    """SPEC §4 Phase 9: The sweep completes in under 10 minutes on a laptop."""
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmpdir:
        run_election_sweep(tmpdir, seed=42)
        run_makespan_sweep(tmpdir, seed=42)
        run_crash_sweep(tmpdir, seed=42)
        run_contention_sweep(tmpdir, seed=42)
        run_calibration(tmpdir, seed=42)

    elapsed = time.time() - t0
    # Assert elapsed < 600 seconds (10 minutes)
    assert elapsed < 600.0, f"Sweep took {elapsed:.2f}s, exceeding 600s limit"
    # Even stricter check: should complete in under 60 seconds
    assert elapsed < 60.0, f"Sweep took {elapsed:.2f}s, exceeding 60s target"
