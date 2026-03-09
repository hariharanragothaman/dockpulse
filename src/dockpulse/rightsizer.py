"""Right-sizing engine that recommends optimal container resource limits."""

from __future__ import annotations

import math

from dockpulse.models import ProfileResult, RightSizeRecommendation, WasteReport

# Reasonable minimums to prevent setting limits too low
_MIN_MEMORY_MB = 16.0
_MIN_CPU = 0.05


class RightSizer:
    """Generates resource-limit recommendations based on observed usage."""

    def __init__(self, headroom_percent: float = 20.0) -> None:
        if headroom_percent < 0:
            raise ValueError("headroom_percent must be non-negative")
        self.headroom_percent = headroom_percent

    def _apply_headroom(self, value: float) -> float:
        return value * (1 + self.headroom_percent / 100.0)

    def recommend(self, profile: ProfileResult) -> RightSizeRecommendation:
        """Produce a right-size recommendation for a single container.

        The recommended limit is the p95 observed usage plus the configured
        headroom percentage, but never below sensible minimums.

        If the container has no explicit limit set (reported as 0), the
        recommendation is based purely on observed usage and the savings
        fields are set to zero.
        """
        rec_mem = max(
            _MIN_MEMORY_MB,
            self._apply_headroom(profile.memory_p95_mb),
        )
        # Round up to the nearest 4 MB for clean compose values
        rec_mem = math.ceil(rec_mem / 4) * 4.0

        rec_cpu = max(
            _MIN_CPU,
            self._apply_headroom(profile.cpu_p95 / 100.0),
        )
        # Round CPU to two decimal places
        rec_cpu = round(rec_cpu, 2)

        current_mem = profile.memory_limit_mb
        current_cpu = profile.peak_cpu / 100.0 if profile.memory_limit_mb == 0 else 0.0

        # For containers without explicit limits we cannot compute savings
        has_mem_limit = current_mem > 0
        mem_savings = max(0.0, current_mem - rec_mem) if has_mem_limit else 0.0
        cpu_savings = max(0.0, current_cpu - rec_cpu) if current_cpu > 0 else 0.0

        return RightSizeRecommendation(
            container_name=profile.name,
            current_memory_limit_mb=current_mem,
            recommended_memory_limit_mb=rec_mem,
            current_cpu_limit=current_cpu,
            recommended_cpu_limit=rec_cpu,
            memory_savings_mb=round(mem_savings, 2),
            cpu_savings=round(cpu_savings, 4),
            headroom_percent=self.headroom_percent,
        )

    def generate_waste_report(self, profiles: list[ProfileResult]) -> WasteReport:
        """Aggregate waste across all profiled containers.

        Containers without explicit limits are included in the recommendations
        but excluded from waste totals (you cannot "waste" an unbounded limit).
        """
        recommendations: list[RightSizeRecommendation] = []
        total_mem_allocated = 0.0
        total_mem_used_p95 = 0.0
        total_cpu_allocated = 0.0
        total_cpu_used_p95 = 0.0

        for profile in profiles:
            rec = self.recommend(profile)
            recommendations.append(rec)

            if profile.memory_limit_mb > 0:
                total_mem_allocated += profile.memory_limit_mb
                total_mem_used_p95 += profile.memory_p95_mb

            if rec.current_cpu_limit > 0:
                total_cpu_allocated += rec.current_cpu_limit
                total_cpu_used_p95 += profile.cpu_p95 / 100.0

        return WasteReport(
            total_memory_allocated_mb=round(total_mem_allocated, 2),
            total_memory_used_p95_mb=round(total_mem_used_p95, 2),
            total_memory_waste_mb=round(max(0.0, total_mem_allocated - total_mem_used_p95), 2),
            total_cpu_allocated=round(total_cpu_allocated, 4),
            total_cpu_used_p95=round(total_cpu_used_p95, 4),
            total_cpu_waste=round(max(0.0, total_cpu_allocated - total_cpu_used_p95), 4),
            recommendations=recommendations,
        )
