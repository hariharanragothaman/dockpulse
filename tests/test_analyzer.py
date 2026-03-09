"""Tests for the analysis engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dockpulse.analyzer import Analyzer
from dockpulse.models import ContainerStats, ProfileResult


def _make_sample(
    *,
    offset_seconds: int = 0,
    cpu: float = 10.0,
    mem_mb: float = 128.0,
    mem_limit_mb: float = 512.0,
) -> ContainerStats:
    """Build a synthetic ContainerStats with tuneable fields."""
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)
    return ContainerStats(
        container_id="abc123",
        name="test-app",
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


class TestPercentileCalculation:
    """Verify that p50/p95/p99 are computed correctly from known data."""

    def test_uniform_values(self) -> None:
        samples = [_make_sample(offset_seconds=i, cpu=50.0, mem_mb=200.0) for i in range(100)]
        result = Analyzer().analyze(samples)

        assert result.cpu_p50 == pytest.approx(50.0)
        assert result.cpu_p95 == pytest.approx(50.0)
        assert result.memory_p50_mb == pytest.approx(200.0)

    def test_ascending_values(self) -> None:
        samples = [
            _make_sample(offset_seconds=i, cpu=float(i), mem_mb=float(i))
            for i in range(1, 101)
        ]
        result = Analyzer().analyze(samples)

        assert result.cpu_p50 == pytest.approx(50.5, abs=0.5)
        assert result.cpu_p95 == pytest.approx(95.05, abs=0.5)
        assert result.cpu_p99 == pytest.approx(99.01, abs=0.5)
        assert result.peak_cpu == 100.0
        assert result.peak_memory_mb == 100.0

    def test_single_sample(self) -> None:
        samples = [_make_sample(cpu=42.0, mem_mb=256.0)]
        result = Analyzer().analyze(samples)

        assert result.cpu_p50 == 42.0
        assert result.cpu_p95 == 42.0
        assert result.memory_p50_mb == 256.0
        assert result.avg_cpu == 42.0

    def test_empty_samples_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            Analyzer().analyze([])


class TestAnomalyDetection:
    """Verify anomaly detection heuristics."""

    def _profile_with_usage(
        self, mem_p95: float, mem_limit: float, cpu_p95: float, peak_cpu: float
    ) -> ProfileResult:
        return ProfileResult(
            container_id="abc",
            name="svc",
            duration_seconds=60,
            samples=[],
            memory_p95_mb=mem_p95,
            memory_limit_mb=mem_limit,
            cpu_p95=cpu_p95,
            peak_cpu=peak_cpu,
            avg_cpu=cpu_p95,
        )

    def test_high_memory_flagged(self) -> None:
        profile = self._profile_with_usage(
            mem_p95=450.0, mem_limit=512.0, cpu_p95=30.0, peak_cpu=50.0
        )
        anomalies = Analyzer().detect_anomalies(profile)
        assert any("Memory pressure" in a for a in anomalies)

    def test_cpu_spike_flagged(self) -> None:
        profile = self._profile_with_usage(
            mem_p95=100.0, mem_limit=512.0, cpu_p95=50.0, peak_cpu=350.0
        )
        anomalies = Analyzer().detect_anomalies(profile)
        assert any("CPU spike" in a for a in anomalies)

    def test_over_provisioned_flagged(self) -> None:
        profile = self._profile_with_usage(
            mem_p95=10.0, mem_limit=512.0, cpu_p95=2.0, peak_cpu=5.0
        )
        anomalies = Analyzer().detect_anomalies(profile)
        assert any("Over-provisioned" in a for a in anomalies)

    def test_healthy_container_no_anomalies(self) -> None:
        profile = self._profile_with_usage(
            mem_p95=200.0, mem_limit=512.0, cpu_p95=40.0, peak_cpu=80.0
        )
        anomalies = Analyzer().detect_anomalies(profile)
        assert anomalies == []
