"""Analysis engine for container profiling data."""

from __future__ import annotations

import math
import statistics
from typing import TYPE_CHECKING

from dockpulse.models import ContainerStats, ProfileResult

if TYPE_CHECKING:
    from collections.abc import Sequence


def _percentile(data: Sequence[float], pct: float) -> float:
    """Calculate the *pct*-th percentile of *data* using linear interpolation.

    Handles edge cases where the dataset is too small for meaningful
    interpolation by falling back to the max value.
    """
    if not data:
        return 0.0
    if len(data) == 1:
        return data[0]

    sorted_data = sorted(data)
    k = (pct / 100) * (len(sorted_data) - 1)
    floor = math.floor(k)
    ceil = math.ceil(k)

    if floor == ceil:
        return sorted_data[floor]

    d0 = sorted_data[floor]
    d1 = sorted_data[ceil]
    return d0 + (d1 - d0) * (k - floor)


class Analyzer:
    """Computes aggregate statistics and detects anomalies in profile data."""

    def analyze(self, samples: list[ContainerStats]) -> ProfileResult:
        """Produce a ``ProfileResult`` from a series of ``ContainerStats``.

        Args:
            samples: Time-ordered stats snapshots for a single container.

        Returns:
            Aggregated profiling result with percentiles and peak values.

        Raises:
            ValueError: If *samples* is empty.
        """
        if not samples:
            raise ValueError("Cannot analyze an empty sample set.")

        first, last = samples[0], samples[-1]
        duration = (last.timestamp - first.timestamp).total_seconds()
        duration = max(duration, 1.0)

        cpu_values = [s.cpu_percent for s in samples]
        mem_values = [s.memory_usage_mb for s in samples]

        return ProfileResult(
            container_id=first.container_id,
            name=first.name,
            duration_seconds=duration,
            samples=samples,
            cpu_p50=_percentile(cpu_values, 50),
            cpu_p95=_percentile(cpu_values, 95),
            cpu_p99=_percentile(cpu_values, 99),
            memory_p50_mb=_percentile(mem_values, 50),
            memory_p95_mb=_percentile(mem_values, 95),
            memory_p99_mb=_percentile(mem_values, 99),
            memory_limit_mb=first.memory_limit_mb,
            peak_memory_mb=max(mem_values),
            avg_cpu=statistics.mean(cpu_values),
            peak_cpu=max(cpu_values),
        )

    def detect_anomalies(self, profile: ProfileResult) -> list[str]:
        """Identify potential resource anomalies in a profile.

        Checks performed:
        - Memory usage consistently above 80 % of limit.
        - CPU spikes exceeding 200 % (multi-core saturation hint).
        - Consistently low resource usage (< 10 % memory *and* CPU) suggesting
          over-provisioning.

        Returns:
            Human-readable anomaly descriptions.
        """
        anomalies: list[str] = []

        if profile.memory_limit_mb > 0:
            mem_ratio = profile.memory_p95_mb / profile.memory_limit_mb
            if mem_ratio > 0.80:
                anomalies.append(
                    f"Memory pressure: p95 usage ({profile.memory_p95_mb:.1f} MB) is "
                    f"{mem_ratio:.0%} of the {profile.memory_limit_mb:.0f} MB limit. "
                    "Risk of OOM-kill under load."
                )

        if profile.peak_cpu > 200.0:
            anomalies.append(
                f"CPU spike: peak CPU reached {profile.peak_cpu:.1f}%, indicating "
                "potential multi-core saturation or a runaway process."
            )

        is_low_memory = (
            profile.memory_limit_mb > 0
            and (profile.memory_p95_mb / profile.memory_limit_mb) < 0.10
        )
        is_low_cpu = profile.cpu_p95 < 10.0

        if is_low_memory and is_low_cpu:
            anomalies.append(
                f"Over-provisioned: container '{profile.name}' uses < 10% of both "
                "CPU and memory. Consider reducing resource limits."
            )

        return anomalies

    def find_bottleneck(self, profiles: list[ProfileResult]) -> str:
        """Identify the most resource-constrained container in a stack.

        The bottleneck is the container whose p95 memory usage is closest to
        its configured limit, or whose p95 CPU is highest when no memory
        limits are set.

        Args:
            profiles: Profile results for multiple containers.

        Returns:
            Name of the bottleneck container with a brief explanation.
        """
        if not profiles:
            return "No profiles to analyze."

        worst_name = profiles[0].name
        worst_score = -1.0
        worst_reason = ""

        for p in profiles:
            if p.memory_limit_mb > 0:
                score = p.memory_p95_mb / p.memory_limit_mb
                reason = (
                    f"memory at {score:.0%} of limit "
                    f"({p.memory_p95_mb:.1f}/{p.memory_limit_mb:.0f} MB)"
                )
            else:
                score = p.cpu_p95 / 100.0
                reason = f"CPU p95 at {p.cpu_p95:.1f}%"

            if score > worst_score:
                worst_score = score
                worst_name = p.name
                worst_reason = reason

        return f"Bottleneck: '{worst_name}' -- {worst_reason}"
