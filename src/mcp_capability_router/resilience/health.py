from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class HealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    RECOVERING = "recovering"


@dataclass(slots=True)
class HealthTracker:
    state: HealthState = HealthState.HEALTHY
    failures: int = 0
    successes: int = 0
    failure_threshold: int = 3

    def record_success(self) -> HealthState:
        self.successes += 1
        self.failures = 0
        self.state = HealthState.HEALTHY
        return self.state

    def record_failure(self) -> HealthState:
        self.failures += 1
        self.state = (
            HealthState.UNHEALTHY
            if self.failures >= self.failure_threshold
            else HealthState.DEGRADED
        )
        return self.state

    def recovering(self) -> None:
        self.state = HealthState.RECOVERING
