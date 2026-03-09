"""Tests for the right-sizing engine."""

from __future__ import annotations

import pytest

from dockpulse.models import ProfileResult
from dockpulse.rightsizer import RightSizer


def _make_profile(
    *,
    name: str = "web",
    mem_p95: float = 200.0,
    mem_limit: float = 512.0,
    cpu_p95: float = 30.0,
    peak_cpu: float = 60.0,
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
        avg_cpu=cpu_p95 * 0.8,
        peak_cpu=peak_cpu,
    )


class TestRecommendWithHeadroom:
    """Verify that recommendations correctly apply headroom."""

    def test_default_headroom(self) -> None:
        sizer = RightSizer(headroom_percent=20.0)
        rec = sizer.recommend(_make_profile(mem_p95=200.0, cpu_p95=30.0))

        # Memory: 200 * 1.2 = 240, rounded up to 4 MB boundary = 240
        assert rec.recommended_memory_limit_mb == 240.0
        # CPU: (30/100) * 1.2 = 0.36
        assert rec.recommended_cpu_limit == 0.36

    def test_custom_headroom(self) -> None:
        sizer = RightSizer(headroom_percent=50.0)
        rec = sizer.recommend(_make_profile(mem_p95=100.0, cpu_p95=20.0))

        # Memory: 100 * 1.5 = 150, already on 4 MB boundary? ceil(150/4)*4 = 152
        assert rec.recommended_memory_limit_mb == 152.0
        # CPU: (20/100) * 1.5 = 0.30
        assert rec.recommended_cpu_limit == 0.30

    def test_memory_savings_calculated(self) -> None:
        sizer = RightSizer(headroom_percent=20.0)
        rec = sizer.recommend(_make_profile(mem_p95=200.0, mem_limit=512.0))

        assert rec.current_memory_limit_mb == 512.0
        assert rec.memory_savings_mb == 512.0 - 240.0

    def test_minimum_memory_floor(self) -> None:
        sizer = RightSizer(headroom_percent=20.0)
        rec = sizer.recommend(_make_profile(mem_p95=5.0, mem_limit=64.0))

        # 5 * 1.2 = 6, but minimum is 16 MB
        assert rec.recommended_memory_limit_mb == 16.0


class TestWasteReport:
    """Verify aggregate waste calculation."""

    def test_total_waste(self) -> None:
        profiles = [
            _make_profile(name="web", mem_p95=200.0, mem_limit=512.0),
            _make_profile(name="db", mem_p95=400.0, mem_limit=1024.0),
        ]
        sizer = RightSizer(headroom_percent=20.0)
        report = sizer.generate_waste_report(profiles)

        assert report.total_memory_allocated_mb == 512.0 + 1024.0
        assert report.total_memory_used_p95_mb == 200.0 + 400.0
        assert report.total_memory_waste_mb == (512.0 + 1024.0) - (200.0 + 400.0)
        assert report.waste_percentage == pytest.approx(
            ((512 + 1024 - 200 - 400) / (512 + 1024)) * 100, abs=0.1
        )

    def test_waste_report_has_recommendations(self) -> None:
        profiles = [_make_profile(name="web"), _make_profile(name="api")]
        report = RightSizer().generate_waste_report(profiles)

        assert len(report.recommendations) == 2
        names = {r.container_name for r in report.recommendations}
        assert names == {"web", "api"}


class TestNoLimitContainer:
    """Verify handling of containers that have no explicit resource limits."""

    def test_no_memory_limit(self) -> None:
        profile = _make_profile(mem_p95=200.0, mem_limit=0.0)
        sizer = RightSizer(headroom_percent=20.0)
        rec = sizer.recommend(profile)

        # Should still produce a recommendation
        assert rec.recommended_memory_limit_mb == 240.0
        # But savings should be zero (no existing limit to save against)
        assert rec.memory_savings_mb == 0.0

    def test_waste_report_excludes_unlimited_from_totals(self) -> None:
        profiles = [
            _make_profile(name="limited", mem_p95=200.0, mem_limit=512.0),
            _make_profile(name="unlimited", mem_p95=300.0, mem_limit=0.0),
        ]
        report = RightSizer().generate_waste_report(profiles)

        # Only the limited container counts toward allocated
        assert report.total_memory_allocated_mb == 512.0
        assert report.total_memory_used_p95_mb == 200.0
