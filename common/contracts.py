"""
Purpose: Data contracts, type definitions, and trace event constants for saga coordination.
Phase: Phase 0
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, TypedDict

# ============================================================================
# Trace Event Name Constants (SPEC.md Section 3.3)
# ============================================================================

SAGA_STARTED = "SAGA_STARTED"
STEP_STARTED = "STEP_STARTED"
STEP_COMPLETED = "STEP_COMPLETED"
STEP_FAILED = "STEP_FAILED"
SAGA_COMPLETED = "SAGA_COMPLETED"
COMP_NEEDED_PUBLISHED = "COMP_NEEDED_PUBLISHED"
ELECTION_START = "ELECTION_START"
LEASE_ACQUIRED = "LEASE_ACQUIRED"
LEASE_LOST = "LEASE_LOST"
LEASE_RENEWED = "LEASE_RENEWED"
LEASE_TAKEOVER = "LEASE_TAKEOVER"
WATCHER_RETRY = "WATCHER_RETRY"
COMP_DISPATCHED = "COMP_DISPATCHED"
COMP_STARTED = "COMP_STARTED"
COMP_COMPLETED = "COMP_COMPLETED"
COMP_FAILED_ATTEMPT = "COMP_FAILED_ATTEMPT"
COMP_DUPLICATE_IGNORED = "COMP_DUPLICATE_IGNORED"
SAGA_COMPENSATED = "SAGA_COMPENSATED"
SAGA_COMPENSATION_FAILED = "SAGA_COMPENSATION_FAILED"
NOTIFICATION_DLQ = "NOTIFICATION_DLQ"
LAMBDA_INVOKE = "LAMBDA_INVOKE"
LAMBDA_END = "LAMBDA_END"
DDB_OPS = "DDB_OPS"
EVENTS_PUT = "EVENTS_PUT"
SFN_TRANSITIONS = "SFN_TRANSITIONS"

ALL_TRACE_EVENTS = {
    SAGA_STARTED,
    STEP_STARTED,
    STEP_COMPLETED,
    STEP_FAILED,
    SAGA_COMPLETED,
    COMP_NEEDED_PUBLISHED,
    ELECTION_START,
    LEASE_ACQUIRED,
    LEASE_LOST,
    LEASE_RENEWED,
    LEASE_TAKEOVER,
    WATCHER_RETRY,
    COMP_DISPATCHED,
    COMP_STARTED,
    COMP_COMPLETED,
    COMP_FAILED_ATTEMPT,
    COMP_DUPLICATE_IGNORED,
    SAGA_COMPENSATED,
    SAGA_COMPENSATION_FAILED,
    NOTIFICATION_DLQ,
    LAMBDA_INVOKE,
    LAMBDA_END,
    DDB_OPS,
    EVENTS_PUT,
    SFN_TRANSITIONS,
}

# ============================================================================
# Status Constants
# ============================================================================

STATUS_RUNNING = "RUNNING"
STATUS_COMPLETED = "COMPLETED"
STATUS_COMPENSATING = "COMPENSATING"
STATUS_COMPENSATED = "COMPENSATED"
STATUS_COMPENSATION_FAILED = "COMPENSATION_FAILED"
STATUS_FAILED = "FAILED"
STATUS_COMP_FAILED = "COMP_FAILED"
STATUS_STARTED = "STARTED"

LEASE_STATUS_ACTIVE = "ACTIVE"
LEASE_STATUS_DONE = "DONE"

PathType = Literal["A", "B", "C", "D"]
WorkloadType = Literal["order", "trainticket", "wide-2", "wide-4", "wide-6"]
CompModeType = Literal["parallel", "lifo"]


# ============================================================================
# Envelope & Fault Contracts (SPEC.md Section 3.1)
# ============================================================================

class StepFault(TypedDict, total=False):
    forward: Optional[Literal["fail"]]
    errorName: Optional[str]
    compFailFirstN: Optional[int]


@dataclass
class SagaEnvelope:
    sagaId: str
    path: PathType
    workload: WorkloadType = "order"
    runTag: str = "default"
    startedAt: int = 0
    payload: Dict[str, Any] = field(default_factory=dict)
    workScale: float = 1.0
    faults: Dict[str, StepFault] = field(default_factory=dict)
    leaderFault: Optional[str] = None
    compMode: CompModeType = "parallel"
    # Legacy compatibility fields
    action: Optional[str] = None
    orderId: Optional[str] = None
    simulateFailure: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "sagaId": self.sagaId,
            "path": self.path,
            "workload": self.workload,
            "runTag": self.runTag,
            "startedAt": self.startedAt,
            "payload": self.payload,
            "workScale": self.workScale,
            "faults": self.faults,
            "leaderFault": self.leaderFault,
            "compMode": self.compMode,
        }
        if self.action is not None:
            d["action"] = self.action
        if self.orderId is not None:
            d["orderId"] = self.orderId
        if self.simulateFailure is not None:
            d["simulateFailure"] = self.simulateFailure
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SagaEnvelope":
        saga_id = data.get("sagaId") or data.get("orderId", "unknown-saga")
        order_id = data.get("orderId") or saga_id
        return cls(
            sagaId=saga_id,
            path=data.get("path", "A"),
            workload=data.get("workload", "order"),
            runTag=data.get("runTag", "default"),
            startedAt=int(data.get("startedAt", 0)),
            payload=data.get("payload", {}),
            workScale=float(data.get("workScale", 1.0)),
            faults=data.get("faults", {}),
            leaderFault=data.get("leaderFault"),
            compMode=data.get("compMode", "parallel"),
            action=data.get("action"),
            orderId=order_id,
            simulateFailure=data.get("simulateFailure"),
        )


# ============================================================================
# DynamoDB Record Contracts (SPEC.md Section 3.2)
# ============================================================================

@dataclass
class SagaRunRecord:
    sagaId: str
    path: PathType
    workload: str
    runTag: str
    status: str
    startedAt: int
    stepCounter: int = 0
    failedAt: Optional[int] = None
    failedStep: Optional[str] = None
    compensatedAt: Optional[int] = None


@dataclass
class SagaStepRecord:
    sagaId: str
    step: str
    status: str
    seq: int = 0
    completedAt: Optional[int] = None
    compensatorFn: Optional[str] = None
    compensateAction: Optional[str] = None
    compensateAfter: List[str] = field(default_factory=list)
    compensateOnFailure: bool = False
    compInvocations: int = 0
    compApplied: int = 0
    compensatedAt: Optional[int] = None


@dataclass
class SagaLeaseRecord:
    sagaId: str
    ownerId: str
    epoch: int
    leaseExpiresAt: int
    status: str
    electedAt: int
