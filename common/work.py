"""
Purpose: Simulated step execution time and fault injection evaluation.
Phase: Phase 1
"""

import random
import time
from typing import Any, Optional
from common.contracts import SagaEnvelope
from common.workloads import NAMED_ERRORS, StepFailure, get_workload


def do_work(ms: int, jitter: int = 0, scale: float = 1.0) -> float:
    """
    Simulates work time sleeping (ms * scale ± jitter), never negative.
    When scale == 0, returns immediately without sleeping (pure overhead check, D4).
    Returns elapsed time in milliseconds.
    """
    if scale <= 0 or ms <= 0:
        return 0.0

    target_ms = (ms * scale) + random.uniform(-jitter, jitter)
    if target_ms < 0:
        target_ms = 0.0

    sleep_sec = target_ms / 1000.0
    start = time.perf_counter()
    time.sleep(sleep_sec)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return elapsed_ms


def apply_faults(
    envelope: SagaEnvelope,
    step_name: str,
    phase: str,  # "forward" or "compensate"
    attempt: int = 1,
) -> None:
    """
    Checks the envelope's fault specification and legacy simulateFailure flag.
    Raises the configured exception if a fault is triggered for this step and attempt.
    """
    # 1. Check legacy simulateFailure alias (D1 / §3.1)
    if phase == "forward" and envelope.simulateFailure:
        # Match error name to workload if available
        wl = get_workload(envelope.workload)
        step_cfg = wl.get_step(step_name)
        err_name = step_cfg.defaultErrorName if step_cfg and step_cfg.defaultErrorName else "StepFailure"
        err_cls = NAMED_ERRORS.get(err_name, StepFailure)
        raise err_cls(f"Simulated forward failure via simulateFailure flag at {step_name}")

    # 2. Check structured faults
    faults = envelope.faults or {}
    # Lookup step case-insensitively
    step_fault: Optional[dict] = None
    for k, v in faults.items():
        if k.lower() == step_name.lower():
            step_fault = v
            break

    if not step_fault:
        return

    if phase == "forward":
        if step_fault.get("forward") == "fail":
            err_name = step_fault.get("errorName")
            if not err_name:
                wl = get_workload(envelope.workload)
                step_cfg = wl.get_step(step_name)
                err_name = step_cfg.defaultErrorName if step_cfg and step_cfg.defaultErrorName else "StepFailure"
            err_cls = NAMED_ERRORS.get(err_name, StepFailure)
            raise err_cls(f"Simulated forward failure at {step_name}: {err_name}")

    elif phase == "compensate":
        comp_fail_n = step_fault.get("compFailFirstN", 0)
        if attempt <= comp_fail_n:
            raise RuntimeError(
                f"Simulated transient compensation failure attempt {attempt}/{comp_fail_n} at step {step_name}"
            )
