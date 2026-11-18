"""
Purpose: Workload step definitions, dependencies, and timing configurations.
Phase: Phase 1
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


class PaymentDeclined(Exception):
    """Business failure raised when payment cannot be processed."""
    pass


class InventoryShortage(Exception):
    """Business failure raised when requested inventory is out of stock."""
    pass


class StepFailure(Exception):
    """Generic forward step execution failure."""
    pass


NAMED_ERRORS = {
    "PaymentDeclined": PaymentDeclined,
    "InventoryShortage": InventoryShortage,
    "StepFailure": StepFailure,
}


@dataclass
class StepConfig:
    name: str
    forwardFn: str
    forwardAction: str
    compensatorFn: str
    compensateAction: str
    compensateAfter: List[str] = field(default_factory=list)
    compensateOnFailure: bool = False
    forwardMs: int = 150
    compensateMs: int = 150
    jitterMs: int = 30
    defaultErrorName: Optional[str] = None


@dataclass
class WorkloadConfig:
    name: str
    steps: List[StepConfig]

    def get_step(self, step_name: str) -> Optional[StepConfig]:
        for s in self.steps:
            if s.name.lower() == step_name.lower():
                return s
        return None


ORDER_WORKLOAD = WorkloadConfig(
    name="order",
    steps=[
        StepConfig(
            name="Order",
            forwardFn="Order",
            forwardAction="create",
            compensatorFn="Order",
            compensateAction="cancel",
            compensateAfter=["*"],
            compensateOnFailure=False,
            forwardMs=150,
            compensateMs=150,
            jitterMs=30,
            defaultErrorName="StepFailure",
        ),
        StepConfig(
            name="Payment",
            forwardFn="Payment",
            forwardAction="charge",
            compensatorFn="Payment",
            compensateAction="compensate",
            compensateAfter=[],
            compensateOnFailure=False,
            forwardMs=150,
            compensateMs=150,
            jitterMs=30,
            defaultErrorName="PaymentDeclined",
        ),
        StepConfig(
            name="Inventory",
            forwardFn="Inventory",
            forwardAction="reserve",
            compensatorFn="Inventory",
            compensateAction="release",
            compensateAfter=[],
            compensateOnFailure=False,
            forwardMs=150,
            compensateMs=150,
            jitterMs=30,
            defaultErrorName="InventoryShortage",
        ),
        StepConfig(
            name="Notification",
            forwardFn="Notification",
            forwardAction="notify",
            compensatorFn="Notification",
            compensateAction="unnotify",
            compensateAfter=[],
            compensateOnFailure=False,
            forwardMs=150,
            compensateMs=150,
            jitterMs=30,
            defaultErrorName="StepFailure",
        ),
    ],
)

TRAINTICKET_WORKLOAD = WorkloadConfig(
    name="trainticket",
    steps=[
        StepConfig(
            name="Order",
            forwardFn="Order",
            forwardAction="book",
            compensatorFn="Order",
            compensateAction="cancel",
            compensateAfter=["*"],
            compensateOnFailure=False,
            forwardMs=100,
            compensateMs=100,
            jitterMs=30,
            defaultErrorName="StepFailure",
        ),
        StepConfig(
            name="Payment",
            forwardFn="Payment",
            forwardAction="pay",
            compensatorFn="Payment",
            compensateAction="refund",
            compensateAfter=["Inventory"],
            compensateOnFailure=False,
            forwardMs=300,
            compensateMs=300,
            jitterMs=30,
            defaultErrorName="PaymentDeclined",
        ),
        StepConfig(
            name="Inventory",
            forwardFn="Inventory",
            forwardAction="seat-allocate",
            compensatorFn="Inventory",
            compensateAction="release",
            compensateAfter=[],
            compensateOnFailure=False,
            forwardMs=200,
            compensateMs=200,
            jitterMs=30,
            defaultErrorName="InventoryShortage",
        ),
        StepConfig(
            name="Notification",
            forwardFn="Notification",
            forwardAction="confirmation",
            compensatorFn="Notification",
            compensateAction="unnotify",
            compensateAfter=[],
            compensateOnFailure=False,
            forwardMs=100,
            compensateMs=100,
            jitterMs=30,
            defaultErrorName="StepFailure",
        ),
    ],
)

WIDE_2_WORKLOAD = WorkloadConfig(
    name="wide-2",
    steps=[
        StepConfig(
            name="Order",
            forwardFn="Order",
            forwardAction="create",
            compensatorFn="Order",
            compensateAction="cancel",
            compensateAfter=["*"],
            compensateOnFailure=False,
            forwardMs=100,
            compensateMs=100,
            jitterMs=10,
            defaultErrorName="StepFailure",
        ),
        StepConfig(
            name="Step1",
            forwardFn="Step1",
            forwardAction="forward",
            compensatorFn="Step1",
            compensateAction="compensate",
            compensateAfter=[],
            compensateOnFailure=False,
            forwardMs=100,
            compensateMs=200,
            jitterMs=10,
            defaultErrorName="StepFailure",
        ),
        StepConfig(
            name="Step2",
            forwardFn="Step2",
            forwardAction="forward",
            compensatorFn="Step2",
            compensateAction="compensate",
            compensateAfter=[],
            compensateOnFailure=False,
            forwardMs=100,
            compensateMs=400,
            jitterMs=10,
            defaultErrorName="StepFailure",
        ),
    ],
)

WIDE_4_WORKLOAD = WorkloadConfig(
    name="wide-4",
    steps=[
        StepConfig(
            name="Order",
            forwardFn="Order",
            forwardAction="create",
            compensatorFn="Order",
            compensateAction="cancel",
            compensateAfter=["*"],
            compensateOnFailure=False,
            forwardMs=100,
            compensateMs=100,
            jitterMs=10,
            defaultErrorName="StepFailure",
        ),
        StepConfig(
            name="Step1",
            forwardFn="Step1",
            forwardAction="forward",
            compensatorFn="Step1",
            compensateAction="compensate",
            compensateAfter=[],
            compensateOnFailure=False,
            forwardMs=100,
            compensateMs=400,
            jitterMs=10,
            defaultErrorName="StepFailure",
        ),
        StepConfig(
            name="Step2",
            forwardFn="Step2",
            forwardAction="forward",
            compensatorFn="Step2",
            compensateAction="compensate",
            compensateAfter=[],
            compensateOnFailure=False,
            forwardMs=100,
            compensateMs=600,
            jitterMs=10,
            defaultErrorName="StepFailure",
        ),
        StepConfig(
            name="Step3",
            forwardFn="Step3",
            forwardAction="forward",
            compensatorFn="Step3",
            compensateAction="compensate",
            compensateAfter=[],
            compensateOnFailure=False,
            forwardMs=100,
            compensateMs=800,
            jitterMs=10,
            defaultErrorName="StepFailure",
        ),
        StepConfig(
            name="Step4",
            forwardFn="Step4",
            forwardAction="forward",
            compensatorFn="Step4",
            compensateAction="compensate",
            compensateAfter=[],
            compensateOnFailure=False,
            forwardMs=100,
            compensateMs=1000,
            jitterMs=10,
            defaultErrorName="StepFailure",
        ),
    ],
)

WIDE_6_WORKLOAD = WorkloadConfig(
    name="wide-6",
    steps=[
        StepConfig(
            name="Order",
            forwardFn="Order",
            forwardAction="create",
            compensatorFn="Order",
            compensateAction="cancel",
            compensateAfter=["*"],
            compensateOnFailure=False,
            forwardMs=100,
            compensateMs=100,
            jitterMs=10,
            defaultErrorName="StepFailure",
        ),
        StepConfig(
            name="Step1",
            forwardFn="Step1",
            forwardAction="forward",
            compensatorFn="Step1",
            compensateAction="compensate",
            compensateAfter=[],
            compensateOnFailure=False,
            forwardMs=100,
            compensateMs=150,
            jitterMs=10,
            defaultErrorName="StepFailure",
        ),
        StepConfig(
            name="Step2",
            forwardFn="Step2",
            forwardAction="forward",
            compensatorFn="Step2",
            compensateAction="compensate",
            compensateAfter=[],
            compensateOnFailure=False,
            forwardMs=100,
            compensateMs=200,
            jitterMs=10,
            defaultErrorName="StepFailure",
        ),
        StepConfig(
            name="Step3",
            forwardFn="Step3",
            forwardAction="forward",
            compensatorFn="Step3",
            compensateAction="compensate",
            compensateAfter=[],
            compensateOnFailure=False,
            forwardMs=100,
            compensateMs=250,
            jitterMs=10,
            defaultErrorName="StepFailure",
        ),
        StepConfig(
            name="Step4",
            forwardFn="Step4",
            forwardAction="forward",
            compensatorFn="Step4",
            compensateAction="compensate",
            compensateAfter=[],
            compensateOnFailure=False,
            forwardMs=100,
            compensateMs=300,
            jitterMs=10,
            defaultErrorName="StepFailure",
        ),
        StepConfig(
            name="Step5",
            forwardFn="Step5",
            forwardAction="forward",
            compensatorFn="Step5",
            compensateAction="compensate",
            compensateAfter=[],
            compensateOnFailure=False,
            forwardMs=100,
            compensateMs=350,
            jitterMs=10,
            defaultErrorName="StepFailure",
        ),
        StepConfig(
            name="Step6",
            forwardFn="Step6",
            forwardAction="forward",
            compensatorFn="Step6",
            compensateAction="compensate",
            compensateAfter=[],
            compensateOnFailure=False,
            forwardMs=100,
            compensateMs=400,
            jitterMs=10,
            defaultErrorName="StepFailure",
        ),
    ],
)

WORKLOADS: Dict[str, WorkloadConfig] = {
    "order": ORDER_WORKLOAD,
    "trainticket": TRAINTICKET_WORKLOAD,
    "wide-2": WIDE_2_WORKLOAD,
    "wide-4": WIDE_4_WORKLOAD,
    "wide-6": WIDE_6_WORKLOAD,
}


def get_workload(name: str = "order") -> WorkloadConfig:
    if name not in WORKLOADS:
        raise KeyError(f"Unknown workload: {name}. Registered: {list(WORKLOADS.keys())}")
    return WORKLOADS[name]
