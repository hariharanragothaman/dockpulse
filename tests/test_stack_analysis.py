"""Tests for stack analysis and session comparison."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from dockpulse.analyzer import Analyzer
from dockpulse.models import ContainerStats, ProfileResult


def _make_sample(
    *,
    name: str = "svc",
    offset_seconds: int = 0,
    cpu: float = 10.0,
    mem_mb: float = 128.0,
    mem_limit_mb: float = 512.0,
) -> ContainerStats:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)
    return ContainerStats(
        container_id="abc123",
        name=name,
        timestamp=ts,
        cpu_percent=cpu,
        memory_usage_mb=mem_mb,
        memory_limit_mb=mem_limit_mb,
        memory_percent=(mem_mb / mem_limit_mb * 100) if mem_limit_mb else 0.0,
        network_rx_mb=0.0,
        network_tx_mb=0.0,
        block_read_mb=0.0,
        block_write_mb=0.0,
        pids=1,
    )


def _make_profile(
    *,
    name: str = "svc",
    mem_p95: float = 200.0,
    mem_limit: float = 512.0,
    cpu_p95: float = 30.0,
    peak_cpu: float = 60.0,
    avg_cpu: float = 25.0,
) -> ProfileResult:
    return ProfileResult(
        container_id="abc",
        name=name,
        duration_seconds=3600,
        samples=[],
        cpu_p50=cpu_p95 * 0.6,
        cpu_p95=cpu_p95,
        cpu_p99=cpu_p95 * 1.1,
        memory_p50_mb=mem_p95 * 0.7,
        memory_p95_mb=mem_p95,
        memory_p99_mb=mem_p95 * 1.05,
        memory_limit_mb=mem_limit,
        peak_memory_mb=mem_p95 * 1.1,
        avg_cpu=avg_cpu,
        peak_cpu=peak_cpu,
    )


class TestAnalyzeStack:
    """Verify stack-level analysis: rankings, bottleneck, recommendations."""

    def test_analyze_stack_rankings(self) -> None:
        profiles = [
            _make_profile(name="web", mem_p95=400.0, mem_limit=512.0, cpu_p95=80.0),
            _make_profile(name="db", mem_p95=100.0, mem_limit=512.0, cpu_p95=10.0),
            _make_profile(name="cache", mem_p95=50.0, mem_limit=256.0, cpu_p95=5.0),
        ]

        result = Analyzer().analyze_stack(profiles)

        ranked_names = [name for name, _score in result.service_rankings]
        assert ranked_names[0] == "web"
        assert len(result.service_rankings) == 3

    def test_analyze_stack_bottleneck(self) -> None:
        profiles = [
            _make_profile(name="web", mem_p95=490.0, mem_limit=512.0, cpu_p95=90.0),
            _make_profile(name="db", mem_p95=100.0, mem_limit=1024.0, cpu_p95=10.0),
        ]

        result = Analyzer().analyze_stack(profiles)

        assert result.bottleneck == "web"
        assert "memory" in result.bottleneck_reason

    def test_analyze_stack_recommendations(self) -> None:
        profiles = [
            _make_profile(name="bloated", mem_p95=10.0, mem_limit=1024.0, cpu_p95=2.0),
        ]

        result = Analyzer().analyze_stack(profiles)

        assert any("over-provisioned" in r.lower() for r in result.recommendations)

    def test_analyze_stack_without_compose(self) -> None:
        profiles = [
            _make_profile(name="web", mem_p95=200.0, mem_limit=512.0),
        ]

        result = Analyzer().analyze_stack(profiles, compose_path=None)

        assert result.dependencies == []
        assert result.bottleneck == "web"
        assert len(result.service_rankings) == 1


class TestCompareSessions:
    """Verify historical session comparison and trend detection."""

    def _build_samples(
        self,
        name: str,
        cpu: float,
        mem_mb: float,
        count: int = 10,
    ) -> list[ContainerStats]:
        return [
            _make_sample(name=name, offset_seconds=i, cpu=cpu, mem_mb=mem_mb)
            for i in range(count)
        ]

    def test_compare_sessions_stable(self) -> None:
        session_a = {"web": self._build_samples("web", cpu=50.0, mem_mb=200.0)}
        session_b = {"web": self._build_samples("web", cpu=51.0, mem_mb=202.0)}

        comparisons = Analyzer().compare_sessions(session_a, session_b, "s1", "s2")

        assert len(comparisons) == 1
        assert comparisons[0].cpu_trend == "stable"
        assert comparisons[0].memory_trend == "stable"

    def test_compare_sessions_increasing(self) -> None:
        session_a = {"web": self._build_samples("web", cpu=50.0, mem_mb=200.0)}
        session_b = {"web": self._build_samples("web", cpu=80.0, mem_mb=350.0)}

        comparisons = Analyzer().compare_sessions(session_a, session_b, "s1", "s2")

        assert comparisons[0].cpu_trend == "increasing"
        assert comparisons[0].memory_trend == "increasing"

    def test_compare_sessions_decreasing(self) -> None:
        session_a = {"web": self._build_samples("web", cpu=80.0, mem_mb=400.0)}
        session_b = {"web": self._build_samples("web", cpu=30.0, mem_mb=150.0)}

        comparisons = Analyzer().compare_sessions(session_a, session_b, "s1", "s2")

        assert comparisons[0].cpu_trend == "decreasing"
        assert comparisons[0].memory_trend == "decreasing"

    def test_compare_sessions_common_only(self) -> None:
        session_a = {
            "web": self._build_samples("web", cpu=50.0, mem_mb=200.0),
            "old-svc": self._build_samples("old-svc", cpu=10.0, mem_mb=50.0),
        }
        session_b = {
            "web": self._build_samples("web", cpu=55.0, mem_mb=210.0),
            "new-svc": self._build_samples("new-svc", cpu=20.0, mem_mb=100.0),
        }

        comparisons = Analyzer().compare_sessions(session_a, session_b, "s1", "s2")

        assert len(comparisons) == 1
        assert comparisons[0].container_name == "web"
