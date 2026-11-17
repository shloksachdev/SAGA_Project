"""
Purpose: System-wide retry, lease timing, and execution policy constants.
Phase: Phase 1
"""

# Compensation retry policy (fair common denominator with Step Functions, D12)
COMP_MAX_ATTEMPTS: int = 3
COMP_INTERVAL_MS: int = 1000

# Path D lease election timing constants
LEASE_TTL_MS: int = 5000
HEARTBEAT_MS: int = LEASE_TTL_MS // 3
WATCH_MAX_ROUNDS: int = 4
WATCH_JITTER_MS: int = 300
