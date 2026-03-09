"""Tests for report generation (JSON and HTML)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from dockpulse.models import RightSizeRecommendation, WasteReport
from dockpulse.reporter import Reporter


def _make_report() -> WasteReport:
    return WasteReport(
        total_memory_allocated_mb=1024.0,
        total_memory_used_p95_mb=400.0,
        total_memory_waste_mb=624.0,
        total_cpu_allocated=4.0,
        total_cpu_used_p95=1.5,
        total_cpu_waste=2.5,
        recommendations=[
            RightSizeRecommendation(
                container_name="web",
                current_memory_limit_mb=512.0,
                recommended_memory_limit_mb=256.0,
                current_cpu_limit=2.0,
                recommended_cpu_limit=0.8,
                memory_savings_mb=256.0,
                cpu_savings=1.2,
                headroom_percent=20.0,
            ),
            RightSizeRecommendation(
                container_name="db",
                current_memory_limit_mb=512.0,
                recommended_memory_limit_mb=384.0,
                current_cpu_limit=2.0,
                recommended_cpu_limit=0.7,
                memory_savings_mb=128.0,
                cpu_savings=1.3,
                headroom_percent=20.0,
            ),
        ],
    )


class TestJsonReport:
    """Verify JSON report generation."""

    def test_to_json_creates_file(self, tmp_path: Path) -> None:
        report = _make_report()
        out = tmp_path / "report.json"

        Reporter().to_json(report, str(out))

        assert out.exists()
        assert out.stat().st_size > 0

    def test_to_json_content(self, tmp_path: Path) -> None:
        report = _make_report()
        out = tmp_path / "report.json"

        Reporter().to_json(report, str(out))

        data = json.loads(out.read_text())
        assert "total_memory_allocated_mb" in data
        assert "total_memory_waste_mb" in data
        assert "waste_percentage" in data
        assert "recommendations" in data
        assert len(data["recommendations"]) == 2
        assert data["total_memory_allocated_mb"] == 1024.0


class TestHtmlReport:
    """Verify HTML report generation."""

    def test_to_html_creates_file(self, tmp_path: Path) -> None:
        report = _make_report()
        out = tmp_path / "report.html"

        Reporter().to_html(report, str(out))

        assert out.exists()
        assert out.stat().st_size > 0

    def test_to_html_contains_data(self, tmp_path: Path) -> None:
        report = _make_report()
        out = tmp_path / "report.html"

        Reporter().to_html(report, str(out))

        html = out.read_text()
        assert "web" in html
        assert "db" in html
        assert "1024" in html
        assert "DockPulse" in html
