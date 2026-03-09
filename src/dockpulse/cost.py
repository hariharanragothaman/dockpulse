"""Cloud cost estimation engine for container resource usage."""

from __future__ import annotations

from dockpulse.models import (
    CloudPricing,
    CostEstimate,
    CostReport,
    ProfileResult,
    RightSizeRecommendation,
)

DEFAULT_MONTHLY_HOURS = 730.0

PRICING_CATALOG: dict[str, CloudPricing] = {
    "aws_fargate": CloudPricing(
        provider="aws_fargate",
        vcpu_per_hour=0.04048,
        memory_per_gb_hour=0.00445,
        region="us-east-1",
    ),
    "gcp_cloud_run": CloudPricing(
        provider="gcp_cloud_run",
        vcpu_per_hour=0.0648,
        memory_per_gb_hour=0.0072,
        region="us-central1",
    ),
    "azure_aci": CloudPricing(
        provider="azure_aci",
        vcpu_per_hour=0.0486,
        memory_per_gb_hour=0.00533,
        region="eastus",
    ),
}

PROVIDER_ALIASES: dict[str, str] = {
    "aws": "aws_fargate",
    "gcp": "gcp_cloud_run",
    "azure": "azure_aci",
    "aws_fargate": "aws_fargate",
    "gcp_cloud_run": "gcp_cloud_run",
    "azure_aci": "azure_aci",
}


def _mb_to_gb(mb: float) -> float:
    return mb / 1024.0


def _cpu_percent_to_vcpu(cpu_percent: float) -> float:
    return cpu_percent / 100.0


def _monthly_cost(vcpu: float, memory_gb: float, pricing: CloudPricing, hours: float) -> float:
    """Calculate monthly cost for a given resource allocation."""
    cpu_cost = vcpu * pricing.vcpu_per_hour * hours
    mem_cost = memory_gb * pricing.memory_per_gb_hour * hours
    return round(cpu_cost + mem_cost, 4)


class CostEstimator:
    """Estimates cloud infrastructure costs from profiling data."""

    def __init__(self, provider: str = "aws", monthly_hours: float = DEFAULT_MONTHLY_HOURS) -> None:
        key = PROVIDER_ALIASES.get(provider, provider)
        if key not in PRICING_CATALOG:
            raise ValueError(
                f"Unknown provider '{provider}'. Available: {', '.join(sorted(PROVIDER_ALIASES))}"
            )
        self._pricing = PRICING_CATALOG[key]
        self._hours = monthly_hours

    @property
    def pricing(self) -> CloudPricing:
        return self._pricing

    def estimate(
        self,
        profiles: list[ProfileResult],
        recommendations: list[RightSizeRecommendation],
    ) -> list[CostEstimate]:
        """Estimate per-container current and optimized costs.

        Current cost is based on the container's configured resource limits
        (or p95 usage if no limits are set). Optimized cost uses the
        right-sizer's recommendations.
        """
        rec_lookup = {r.container_name: r for r in recommendations}
        estimates: list[CostEstimate] = []

        for profile in profiles:
            current_mem_gb = _mb_to_gb(
                profile.memory_limit_mb if profile.memory_limit_mb > 0 else profile.memory_p95_mb
            )
            current_vcpu = _cpu_percent_to_vcpu(
                profile.peak_cpu if profile.peak_cpu > 0 else profile.cpu_p95
            )

            current_cost = _monthly_cost(current_vcpu, current_mem_gb, self._pricing, self._hours)

            rec = rec_lookup.get(profile.name)
            if rec:
                opt_mem_gb = _mb_to_gb(rec.recommended_memory_limit_mb)
                opt_vcpu = rec.recommended_cpu_limit
            else:
                opt_mem_gb = _mb_to_gb(profile.memory_p95_mb)
                opt_vcpu = _cpu_percent_to_vcpu(profile.cpu_p95)

            optimized_cost = _monthly_cost(opt_vcpu, opt_mem_gb, self._pricing, self._hours)
            savings = max(current_cost - optimized_cost, 0.0)

            estimates.append(
                CostEstimate(
                    container_name=profile.name,
                    current_monthly_cost=round(current_cost, 2),
                    optimized_monthly_cost=round(optimized_cost, 2),
                    monthly_savings=round(savings, 2),
                    provider=self._pricing.provider,
                )
            )

        return estimates

    def generate_report(
        self,
        profiles: list[ProfileResult],
        recommendations: list[RightSizeRecommendation],
    ) -> CostReport:
        """Generate a full cost report with totals."""
        estimates = self.estimate(profiles, recommendations)

        total_current = sum(e.current_monthly_cost for e in estimates)
        total_optimized = sum(e.optimized_monthly_cost for e in estimates)
        total_savings = sum(e.monthly_savings for e in estimates)

        return CostReport(
            estimates=estimates,
            total_current_cost=round(total_current, 2),
            total_optimized_cost=round(total_optimized, 2),
            total_savings=round(total_savings, 2),
            provider=self._pricing.provider,
            monthly_hours=self._hours,
        )
