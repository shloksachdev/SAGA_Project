"""
Purpose: Service operation metering and telemetry wrapper (D14, §3.3).
Phase: Phase 1
"""

from contextlib import contextmanager
import time
from typing import Dict, Iterator, Optional
from common.contracts import DDB_OPS, EVENTS_PUT, LAMBDA_END
from common.trace import emit, now_ms


class MetricsCollector:
    def __init__(self, saga_id: str, actor: str, path: Optional[str] = None):
        self.saga_id = saga_id
        self.actor = actor
        self.path = path
        self.ddb_ops: Dict[str, int] = {}
        self.events_count: int = 0
        self.start_ns = time.time_ns()

    def record_ddb_op(self, op_name: str, table_name: Optional[str] = None) -> None:
        if table_name == "SagaTrace":
            return  # Exclude instrumentation overhead (Task 7)
        self.ddb_ops[op_name] = self.ddb_ops.get(op_name, 0) + 1

    def record_events(self, count: int = 1) -> None:
        self.events_count += count

    def flush(self) -> None:
        duration_ms = (time.time_ns() - self.start_ns) // 1_000_000

        if self.ddb_ops:
            emit(
                self.saga_id,
                DDB_OPS,
                actor=self.actor,
                path=self.path,
                ops=self.ddb_ops,
            )

        if self.events_count > 0:
            emit(
                self.saga_id,
                EVENTS_PUT,
                actor=self.actor,
                path=self.path,
                count=self.events_count,
            )

        emit(
            self.saga_id,
            LAMBDA_END,
            actor=self.actor,
            path=self.path,
            durationMs=duration_ms,
            billedMs=max(1, duration_ms),
        )


@contextmanager
def metered_invocation(saga_id: str, actor: str, path: Optional[str] = None) -> Iterator[MetricsCollector]:
    collector = MetricsCollector(saga_id, actor, path)
    try:
        yield collector
    finally:
        try:
            collector.flush()
        except Exception:
            pass
