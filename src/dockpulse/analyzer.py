"""Analysis engine for container profiling data."""

from __future__ import annotations

import math
import statistics
from typing import TYPE_CHECKING

from ruamel.yaml import YAML

if TYPE_CHECKING:
    from collections.abc import Sequence

from dockpulse.models import (
    ContainerStats,
    HistoricalComparison,
    ProfileResult,
    ServiceDependency,
    StackAnalysis,
)


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
            profile.memory_limit_mb > 0 and (profile.memory_p95_mb / profile.memory_limit_mb) < 0.10
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

    # ------------------------------------------------------------------
    # Stack-level analysis
    # ------------------------------------------------------------------

    def analyze_stack(
        self,
        profiles: list[ProfileResult],
        compose_path: str | None = None,
    ) -> StackAnalysis:
        """Perform comprehensive analysis of a multi-container stack.

        Analyzes resource usage patterns, identifies dependencies (from compose file),
        finds bottlenecks, ranks services by resource pressure, and generates
        actionable recommendations.
        """
        dependencies: list[ServiceDependency] = []
        if compose_path is not None:
            dependencies = self._parse_compose_dependencies(compose_path)

        pressure_scores: list[tuple[str, float]] = []
        for p in profiles:
            mem_component = 0.0
            if p.memory_limit_mb > 0:
                mem_component = p.memory_p95_mb / p.memory_limit_mb
            cpu_component = p.cpu_p95 / 100.0
            score = mem_component * 0.6 + cpu_component * 0.4
            pressure_scores.append((p.name, score))

        service_rankings = sorted(pressure_scores, key=lambda t: t[1], reverse=True)

        bottleneck_name = ""
        bottleneck_reason = ""
        if service_rankings:
            bottleneck_name = service_rankings[0][0]
            bp = next(p for p in profiles if p.name == bottleneck_name)
            if bp.memory_limit_mb > 0:
                mem_ratio = bp.memory_p95_mb / bp.memory_limit_mb
                bottleneck_reason = f"memory at {mem_ratio:.0%} of limit"
            else:
                bottleneck_reason = f"CPU p95 at {bp.cpu_p95:.1f}%"

        total_cpu = sum(p.avg_cpu for p in profiles)
        total_memory = sum(p.memory_p95_mb for p in profiles)

        recommendations = self._generate_stack_recommendations(
            profiles,
            dependencies,
            service_rankings,
        )

        return StackAnalysis(
            profiles=profiles,
            dependencies=dependencies,
            bottleneck=bottleneck_name,
            bottleneck_reason=bottleneck_reason,
            total_cpu_usage=total_cpu,
            total_memory_usage_mb=total_memory,
            service_rankings=service_rankings,
            recommendations=recommendations,
        )

    # ------------------------------------------------------------------
    # Session comparison
    # ------------------------------------------------------------------

    def compare_sessions(
        self,
        session_a: dict[str, list[ContainerStats]],
        session_b: dict[str, list[ContainerStats]],
        session_a_id: str,
        session_b_id: str,
    ) -> list[HistoricalComparison]:
        """Compare resource usage between two profiling sessions.

        Returns comparison for each container that appears in both sessions,
        including trend detection (increasing/decreasing/stable).
        """
        common_containers = set(session_a) & set(session_b)
        comparisons: list[HistoricalComparison] = []

        for name in sorted(common_containers):
            profile_a = self.analyze(session_a[name])
            profile_b = self.analyze(session_b[name])

            cpu_delta = profile_b.cpu_p95 - profile_a.cpu_p95
            mem_delta = profile_b.memory_p95_mb - profile_a.memory_p95_mb

            cpu_trend = self._detect_trend(cpu_delta, profile_a.cpu_p95)
            memory_trend = self._detect_trend(mem_delta, profile_a.memory_p95_mb)

            comparisons.append(
                HistoricalComparison(
                    session_a_id=session_a_id,
                    session_b_id=session_b_id,
                    container_name=name,
                    cpu_p95_delta=cpu_delta,
                    memory_p95_delta_mb=mem_delta,
                    cpu_trend=cpu_trend,
                    memory_trend=memory_trend,
                )
            )

        return comparisons

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_compose_dependencies(self, compose_path: str) -> list[ServiceDependency]:
        """Extract service dependencies from a docker-compose.yml file."""
        yaml = YAML()
        with open(compose_path) as fh:
            compose = yaml.load(fh)

        deps: list[ServiceDependency] = []
        services: dict = compose.get("services", {})

        for svc_name, svc_cfg in services.items():
            if not isinstance(svc_cfg, dict):
                continue

            for target in self._extract_depends_on(svc_cfg):
                deps.append(
                    ServiceDependency(source=svc_name, target=target, dependency_type="depends_on")
                )

            for target in svc_cfg.get("links", []):
                link_target = target.split(":")[0]
                deps.append(
                    ServiceDependency(source=svc_name, target=link_target, dependency_type="link")
                )

        network_members: dict[str, list[str]] = {}
        for svc_name, svc_cfg in services.items():
            if not isinstance(svc_cfg, dict):
                continue
            nets = svc_cfg.get("networks")
            if isinstance(nets, list):
                net_names = nets
            elif isinstance(nets, dict):
                net_names = list(nets.keys())
            else:
                continue
            for net in net_names:
                network_members.setdefault(net, []).append(svc_name)

        for _net, members in network_members.items():
            for i, a in enumerate(members):
                for b in members[i + 1 :]:
                    deps.append(ServiceDependency(source=a, target=b, dependency_type="network"))

        volume_members: dict[str, list[str]] = {}
        for svc_name, svc_cfg in services.items():
            if not isinstance(svc_cfg, dict):
                continue
            for vol in svc_cfg.get("volumes", []):
                vol_name = vol.split(":")[0] if isinstance(vol, str) else vol.get("source", "")
                if vol_name:
                    volume_members.setdefault(vol_name, []).append(svc_name)

        for _vol, members in volume_members.items():
            for i, a in enumerate(members):
                for b in members[i + 1 :]:
                    deps.append(ServiceDependency(source=a, target=b, dependency_type="volume"))

        return deps

    @staticmethod
    def _extract_depends_on(svc_cfg: dict) -> list[str]:
        """Normalise the various depends_on formats into a list of service names."""
        depends_on = svc_cfg.get("depends_on")
        if depends_on is None:
            return []
        if isinstance(depends_on, list):
            return list(depends_on)
        if isinstance(depends_on, dict):
            return list(depends_on.keys())
        return []

    @staticmethod
    def _detect_trend(delta: float, baseline: float) -> str:
        """Return 'increasing', 'decreasing', or 'stable' based on 5 % threshold."""
        if baseline == 0:
            return "increasing" if delta > 0 else "stable"
        ratio = delta / baseline
        if ratio > 0.05:
            return "increasing"
        if ratio < -0.05:
            return "decreasing"
        return "stable"

    @staticmethod
    def _generate_stack_recommendations(
        profiles: list[ProfileResult],
        dependencies: list[ServiceDependency],
        rankings: list[tuple[str, float]],
    ) -> list[str]:
        """Build actionable, natural-language recommendations for a stack."""
        recs: list[str] = []

        if rankings:
            top_name, _top_score = rankings[0]
            top_profile = next(p for p in profiles if p.name == top_name)
            if top_profile.memory_limit_mb > 0:
                mem_pct = top_profile.memory_p95_mb / top_profile.memory_limit_mb
                if mem_pct > 0.70:
                    recs.append(
                        f"Service '{top_name}' is the bottleneck - memory at "
                        f"{mem_pct:.0%} of limit. Consider increasing memory "
                        "limit or optimizing the application."
                    )

        for p in profiles:
            if p.memory_limit_mb <= 0:
                continue
            mem_ratio = p.memory_p95_mb / p.memory_limit_mb
            if mem_ratio < 0.10:
                savings = p.memory_limit_mb - p.memory_p95_mb
                recs.append(
                    f"Service '{p.name}' is over-provisioned - using only "
                    f"{mem_ratio:.0%} of allocated memory. Reduce limits to "
                    f"save {savings:.0f} MB."
                )

        network_deps = [d for d in dependencies if d.dependency_type == "network"]
        profile_map = {p.name: p for p in profiles}
        checked_pairs: set[tuple[str, str]] = set()
        for dep in network_deps:
            pair = (min(dep.source, dep.target), max(dep.source, dep.target))
            if pair in checked_pairs:
                continue
            checked_pairs.add(pair)
            pa = profile_map.get(dep.source)
            pb = profile_map.get(dep.target)
            if pa is None or pb is None:
                continue
            if pa.memory_limit_mb > 0 and pb.memory_limit_mb > 0:
                ratio_a = pa.memory_p95_mb / pa.memory_limit_mb
                ratio_b = pb.memory_p95_mb / pb.memory_limit_mb
                if abs(ratio_a - ratio_b) > 0.30:
                    recs.append(
                        f"Services '{dep.source}' and '{dep.target}' share a "
                        "network but have unbalanced resource allocation."
                    )

        return recs
