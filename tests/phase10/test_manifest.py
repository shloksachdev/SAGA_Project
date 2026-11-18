"""
Purpose: Acceptance tests for manifest generation and provenance auditing (SPEC §4 Phase 10 Task 2).
Phase: Phase 10
"""

import json
import os
import tempfile
import time
import pytest

from harness.manifest import (
    append_to_experiment_log,
    compute_file_sha256,
    create_manifest,
    get_docker_version,
    get_git_info,
    get_host_ram_gb,
    get_installed_libraries,
    get_localstack_version,
    write_manifest,
)


def test_compute_sha256_deterministic():
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write("test provenance content 12345")
        f_path = f.name

    try:
        h1 = compute_file_sha256(f_path)
        h2 = compute_file_sha256(f_path)
        assert len(h1) == 64
        assert h1 == h2
    finally:
        os.remove(f_path)


def test_git_info_structure():
    info = get_git_info()
    assert "commit" in info
    assert "branch" in info
    assert "is_dirty" in info
    assert "analysis_plan_commit" in info
    assert len(info["commit"]) >= 7 or info["commit"] == "unknown"


def test_environment_probes():
    ls_ver = get_localstack_version()
    assert isinstance(ls_ver, str)
    assert len(ls_ver) > 0

    doc_ver = get_docker_version()
    assert isinstance(doc_ver, str)
    assert len(doc_ver) > 0

    ram = get_host_ram_gb()
    assert ram > 1.0

    libs = get_installed_libraries()
    for required in ("boto3", "simpy", "scipy", "numpy", "matplotlib"):
        assert required in libs
        assert libs[required] != "not_installed"


def test_manifest_creation_and_writing():
    start = time.time() - 10.0
    end = time.time()
    mock_records = [
        {"warmup": True, "timedOut": False, "consistent": True},
        {"warmup": False, "timedOut": False, "consistent": True},
        {"warmup": False, "timedOut": False, "consistent": True},
        {"warmup": False, "timedOut": True, "consistent": False},
    ]

    manifest = create_manifest(
        run_tag="test-manifest-run",
        config_path="experiments/configs/smoke.json",
        start_time=start,
        end_time=end,
        records=mock_records,
        seed=42,
    )

    # Verify counts
    assert manifest["counts"]["totalRuns"] == 4
    assert manifest["counts"]["warmupCount"] == 1
    assert manifest["counts"]["measurementCount"] == 3
    assert manifest["counts"]["timeoutCount"] == 1
    assert manifest["counts"]["consistencyRate"] == 75.0

    # Verify sha256 fields
    assert len(manifest["configSha256"]) == 64
    assert len(manifest["analysisPlanSha256"]) == 64

    # Verify write
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "test.manifest.json")
        written = write_manifest(manifest, out_path)
        assert os.path.exists(written)

        with open(written, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["runTag"] == "test-manifest-run"
            assert data["counts"]["totalRuns"] == 4


def test_append_to_experiment_log():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = os.path.join(tmpdir, "EXPERIMENT_LOG.md")
        mock_manifest = {
            "runTag": "audit-test-tag",
            "configPath": "experiments/configs/smoke.json",
            "configSha256": "abc1234567890def",
            "analysisPlanSha256": "fed0987654321cba",
            "startEpochMs": 1700000000000,
            "wallClockDurationSec": 45.2,
            "counts": {
                "totalRuns": 36,
                "measurementCount": 32,
                "warmupCount": 4,
                "timeoutCount": 0,
                "errorCount": 0,
                "consistencyRate": 100.0,
            },
            "git": {
                "commit": "f344490",
                "branch": "master",
                "is_dirty": False,
                "analysis_plan_commit": "2ec6cac",
            },
            "localstack": {"version": "3.8.0", "endpoint": "http://localhost:4566"},
            "host": {
                "os": "Windows-11",
                "cpuCount": 12,
                "ramGb": 16.0,
                "dockerVersion": "Docker 29.4.0",
            },
        }

        append_to_experiment_log(mock_manifest, log_path=log_file)
        assert os.path.exists(log_file)
        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()
            assert "audit-test-tag" in content
            assert "Total Runs: 36" in content
            assert "f344490" in content
