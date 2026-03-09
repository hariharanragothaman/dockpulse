"""Rewrite Docker Compose files with right-sized resource limits."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import TYPE_CHECKING

from ruamel.yaml import YAML

if TYPE_CHECKING:
    from dockpulse.models import RightSizeRecommendation


class ComposeRewriter:
    """Reads a Docker Compose file, injects resource recommendations, and writes
    an optimised version while preserving comments and formatting."""

    def __init__(self) -> None:
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self._yaml.default_flow_style = False

    def rewrite(
        self,
        compose_path: str,
        recommendations: list[RightSizeRecommendation],
        output_path: str,
    ) -> None:
        """Apply resource recommendations to a compose file.

        For each recommendation whose ``container_name`` matches a service key,
        the ``deploy.resources.limits`` and ``deploy.resources.reservations``
        sections are created or updated.

        Args:
            compose_path: Path to the original ``docker-compose.yml``.
            recommendations: Right-sizing recommendations to apply.
            output_path: Destination path for the optimised file.
        """
        src = Path(compose_path)
        doc = self._yaml.load(src)

        services = doc.get("services", {})
        rec_lookup = {r.container_name: r for r in recommendations}

        for service_name, service_cfg in services.items():
            rec = rec_lookup.get(service_name)
            if rec is None:
                continue

            deploy = service_cfg.setdefault("deploy", {})
            resources = deploy.setdefault("resources", {})

            limits = resources.setdefault("limits", {})
            limits["memory"] = f"{int(rec.recommended_memory_limit_mb)}M"
            if rec.recommended_cpu_limit > 0:
                limits["cpus"] = str(rec.recommended_cpu_limit)

            reservations = resources.setdefault("reservations", {})
            # Reservation = 50 % of the recommended limit (a common heuristic)
            reservation_mem = max(16, int(rec.recommended_memory_limit_mb * 0.5))
            reservations["memory"] = f"{reservation_mem}M"

        dest = Path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("w") as fh:
            self._yaml.dump(doc, fh)

    def diff(self, original_path: str, optimized_path: str) -> str:
        """Return a unified diff between the original and optimised compose files.

        The output is human-readable and suitable for terminal display.
        """
        original_lines = Path(original_path).read_text().splitlines(keepends=True)
        optimized_lines = Path(optimized_path).read_text().splitlines(keepends=True)

        diff_lines = difflib.unified_diff(
            original_lines,
            optimized_lines,
            fromfile=original_path,
            tofile=optimized_path,
            lineterm="",
        )
        return "\n".join(diff_lines)
