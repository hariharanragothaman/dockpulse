"""Tests for the cloud cost estimation engine."""

from __future__ import annotations

import pytest

from dockpulse.cost import PRICING_CATALOG, CostEstimator, _mb_to_gb, _monthly_cost
from dockpulse.models import ProfileResult, RightSizeRecommendation


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


def _make_recommendation(
    *,
    name: str = "web",
    rec_mem: float = 240.0,
    rec_cpu: float = 0.36,
) -> RightSizeRecommendation:
    return RightSizeRecommendation(
        container_name=name,
        current_memory_limit_mb=512.0,
        recommended_memory_limit_mb=rec_mem,
        current_cpu_limit=0.6,
        recommended_cpu_limit=rec_cpu,
        memory_savings_mb=512.0 - rec_mem,
        cpu_savings=0.6 - rec_cpu,
        headroom_percent=20.0,
    )


class TestHelpers:
    def test_mb_to_gb(self) -> None:
        assert _mb_to_gb(1024.0) == 1.0
        assert _mb_to_gb(512.0) == 0.5

    def test_monthly_cost(self) -> None:
        pricing = PRICING_CATALOG["aws_fargate"]
        cost = _monthly_cost(1.0, 1.0, pricing, 730.0)
        expected = (1.0 * 0.04048 * 730) + (1.0 * 0.00445 * 730)
        assert cost == pytest.approx(expected, abs=0.01)


class TestCostEstimator:
    def test_default_provider(self) -> None:
        est = CostEstimator()
        assert est.pricing.provider == "aws_fargate"

    def test_provider_alias(self) -> None:
        est = CostEstimator(provider="gcp")
        assert est.pricing.provider == "gcp_cloud_run"

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown provider"):
            CostEstimator(provider="ibm_cloud")

    def test_estimate_produces_savings(self) -> None:
        profiles = [_make_profile(name="web", mem_p95=200.0, mem_limit=512.0, peak_cpu=60.0)]
        recs = [_make_recommendation(name="web", rec_mem=240.0, rec_cpu=0.36)]
        est = CostEstimator(provider="aws")
        estimates = est.estimate(profiles, recs)

        assert len(estimates) == 1
        e = estimates[0]
        assert e.container_name == "web"
        assert e.current_monthly_cost > 0
        assert e.optimized_monthly_cost > 0
        assert e.monthly_savings >= 0
        assert e.current_monthly_cost >= e.optimized_monthly_cost

    def test_estimate_without_recommendations(self) -> None:
        profiles = [_make_profile(name="web", mem_p95=200.0, mem_limit=512.0)]
        est = CostEstimator(provider="aws")
        estimates = est.estimate(profiles, [])

        assert len(estimates) == 1
        e = estimates[0]
        assert e.monthly_savings >= 0

    def test_no_limit_uses_p95(self) -> None:
        profiles = [_make_profile(name="web", mem_p95=200.0, mem_limit=0.0, peak_cpu=0.0)]
        est = CostEstimator(provider="aws")
        estimates = est.estimate(profiles, [])

        assert len(estimates) == 1
        e = estimates[0]
        assert e.current_monthly_cost > 0

    def test_generate_report_totals(self) -> None:
        profiles = [
            _make_profile(name="web", mem_p95=200.0, mem_limit=512.0, peak_cpu=60.0),
            _make_profile(name="api", mem_p95=100.0, mem_limit=256.0, peak_cpu=40.0),
        ]
        recs = [
            _make_recommendation(name="web", rec_mem=240.0, rec_cpu=0.36),
            _make_recommendation(name="api", rec_mem=120.0, rec_cpu=0.24),
        ]
        est = CostEstimator(provider="aws")
        report = est.generate_report(profiles, recs)

        assert len(report.estimates) == 2
        assert report.total_current_cost == pytest.approx(
            sum(e.current_monthly_cost for e in report.estimates), abs=0.01
        )
        assert report.total_optimized_cost == pytest.approx(
            sum(e.optimized_monthly_cost for e in report.estimates), abs=0.01
        )
        assert report.total_savings == pytest.approx(
            sum(e.monthly_savings for e in report.estimates), abs=0.01
        )
        assert report.provider == "aws_fargate"

    def test_all_providers_have_pricing(self) -> None:
        for _key, pricing in PRICING_CATALOG.items():
            assert pricing.vcpu_per_hour > 0
            assert pricing.memory_per_gb_hour > 0
            assert pricing.region != ""

    def test_multi_provider_comparison(self) -> None:
        profiles = [_make_profile(name="web", mem_p95=200.0, mem_limit=512.0, peak_cpu=60.0)]
        recs = [_make_recommendation(name="web")]

        costs = {}
        for provider in ("aws", "gcp", "azure"):
            est = CostEstimator(provider=provider)
            report = est.generate_report(profiles, recs)
            costs[provider] = report.total_current_cost

        assert len(costs) == 3
        assert all(c > 0 for c in costs.values())

    def test_custom_monthly_hours(self) -> None:
        profiles = [_make_profile(name="web")]
        recs = [_make_recommendation(name="web")]

        est_full = CostEstimator(provider="aws", monthly_hours=730.0)
        est_half = CostEstimator(provider="aws", monthly_hours=365.0)

        report_full = est_full.generate_report(profiles, recs)
        report_half = est_half.generate_report(profiles, recs)

        assert report_full.total_current_cost == pytest.approx(
            report_half.total_current_cost * 2, abs=0.05
        )
