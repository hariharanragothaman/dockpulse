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


@dataclass(frozen=True, slots=True)
class ProfileSession:
    """Metadata for a profiling session."""

    session_id: str
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int
    interval_seconds: float
    container_count: int
    sample_count: int
    status: str  # "running", "completed", "interrupted"


@dataclass(slots=True)
class ServiceDependency:
    """A dependency relationship between two Compose services."""

    source: str
    target: str
    dependency_type: str  # "depends_on", "network", "volume", "link"


@dataclass(slots=True)
class StackAnalysis:
    """Analysis result for an entire multi-container stack."""

    profiles: list[ProfileResult]
    dependencies: list[ServiceDependency]
    bottleneck: str
    bottleneck_reason: str
    total_cpu_usage: float
    total_memory_usage_mb: float
    service_rankings: list[tuple[str, float]]  # (name, resource_pressure_score)
    recommendations: list[str]


@dataclass(frozen=True, slots=True)
class HistoricalComparison:
    """Comparison between two profiling sessions."""

    session_a_id: str
    session_b_id: str
    container_name: str
    cpu_p95_delta: float
    memory_p95_delta_mb: float
    cpu_trend: str  # "increasing", "decreasing", "stable"
    memory_trend: str  # "increasing", "decreasing", "stable"


@dataclass(frozen=True, slots=True)
class CloudPricing:
    """Pricing rates for a cloud container service."""

    provider: str  # "aws_fargate", "gcp_cloud_run", "azure_aci"
    vcpu_per_hour: float
    memory_per_gb_hour: float
    region: str


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """Cost estimate for a single container."""

    container_name: str
    current_monthly_cost: float
    optimized_monthly_cost: float
    monthly_savings: float
    provider: str


@dataclass(slots=True)
class CostReport:
    """Aggregate cost report across all containers."""

    estimates: list[CostEstimate] = field(default_factory=list)
    total_current_cost: float = 0.0
    total_optimized_cost: float = 0.0
    total_savings: float = 0.0
    provider: str = ""
    monthly_hours: float = 730.0


@dataclass(frozen=True, slots=True)
class StartupProfile:
    """Startup timing for a container."""

    container_name: str
    image: str
    create_to_running_ms: float
    running_to_healthy_ms: float
    total_startup_ms: float
    image_size_mb: float
    has_healthcheck: bool
