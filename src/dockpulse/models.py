"""Data models for DockPulse container profiling and right-sizing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class ContainerStats:
    """A single point-in-time resource snapshot for one container."""

    container_id: str
    name: str
    timestamp: datetime
    cpu_percent: float
    memory_usage_mb: float
    memory_limit_mb: float
    memory_percent: float
    network_rx_mb: float
    network_tx_mb: float
    block_read_mb: float
    block_write_mb: float
    pids: int


@dataclass(slots=True)
class ProfileResult:
    """Aggregated profiling statistics for a container over a time window."""

    container_id: str
    name: str
    duration_seconds: float
    samples: list[ContainerStats]

    cpu_p50: float = 0.0
    cpu_p95: float = 0.0
    cpu_p99: float = 0.0

    memory_p50_mb: float = 0.0
    memory_p95_mb: float = 0.0
    memory_p99_mb: float = 0.0

    memory_limit_mb: float = 0.0
    peak_memory_mb: float = 0.0
    avg_cpu: float = 0.0
    peak_cpu: float = 0.0


@dataclass(frozen=True, slots=True)
class RightSizeRecommendation:
    """A resource limit recommendation for a single container."""

    container_name: str
    current_memory_limit_mb: float
    recommended_memory_limit_mb: float
    current_cpu_limit: float
    recommended_cpu_limit: float
    memory_savings_mb: float
    cpu_savings: float
    headroom_percent: float


@dataclass(slots=True)
class WasteReport:
    """Aggregate resource waste across all profiled containers."""

    total_memory_allocated_mb: float
    total_memory_used_p95_mb: float
    total_memory_waste_mb: float
    total_cpu_allocated: float
    total_cpu_used_p95: float
    total_cpu_waste: float
    recommendations: list[RightSizeRecommendation] = field(default_factory=list)

    @property
    def waste_percentage(self) -> float:
        """Overall memory waste as a percentage of total allocated."""
        if self.total_memory_allocated_mb == 0:
            return 0.0
        return (self.total_memory_waste_mb / self.total_memory_allocated_mb) * 100.0
