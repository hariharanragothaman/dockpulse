"""Tests for the Docker Compose rewriter."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

from dockpulse.compose_rewriter import ComposeRewriter
from dockpulse.models import RightSizeRecommendation


def _make_rec(
    name: str,
    mem_limit: float = 256.0,
    cpu_limit: float = 0.5,
) -> RightSizeRecommendation:
    return RightSizeRecommendation(
        container_name=name,
        current_memory_limit_mb=512.0,
        recommended_memory_limit_mb=mem_limit,
        current_cpu_limit=1.0,
        recommended_cpu_limit=cpu_limit,
        memory_savings_mb=512.0 - mem_limit,
        cpu_savings=1.0 - cpu_limit,
        headroom_percent=20.0,
    )


_BASIC_COMPOSE = """\
version: "3.8"
services:
  web:
    image: nginx:latest
    ports:
      - "80:80"
"""


class TestComposeRewriter:
    """Verify that ComposeRewriter injects resource limits correctly."""

    def test_rewrite_adds_resource_limits(self, tmp_path: Path) -> None:
        src = tmp_path / "docker-compose.yml"
        dst = tmp_path / "docker-compose.optimized.yml"
        src.write_text(_BASIC_COMPOSE)

        rewriter = ComposeRewriter()
        rewriter.rewrite(str(src), [_make_rec("web", mem_limit=256.0, cpu_limit=0.5)], str(dst))

        content = dst.read_text()
        assert "limits:" in content
        assert "256M" in content
        assert "0.5" in content
        assert "reservations:" in content

    def test_rewrite_preserves_existing_content(self, tmp_path: Path) -> None:
        src = tmp_path / "docker-compose.yml"
        dst = tmp_path / "docker-compose.optimized.yml"
        src.write_text(_BASIC_COMPOSE)

        rewriter = ComposeRewriter()
        rewriter.rewrite(str(src), [_make_rec("web")], str(dst))

        content = dst.read_text()
        assert "nginx:latest" in content
        assert '"80:80"' in content or "80:80" in content

    def test_rewrite_updates_existing_limits(self, tmp_path: Path) -> None:
        compose_with_limits = """\
version: "3.8"
services:
  web:
    image: nginx:latest
    deploy:
      resources:
        limits:
          memory: 1024M
          cpus: "2.0"
"""
        src = tmp_path / "docker-compose.yml"
        dst = tmp_path / "docker-compose.optimized.yml"
        src.write_text(compose_with_limits)

        rewriter = ComposeRewriter()
        rewriter.rewrite(str(src), [_make_rec("web", mem_limit=256.0, cpu_limit=0.5)], str(dst))

        content = dst.read_text()
        assert "256M" in content
        assert "1024M" not in content

    def test_diff_shows_changes(self, tmp_path: Path) -> None:
        src = tmp_path / "docker-compose.yml"
        dst = tmp_path / "docker-compose.optimized.yml"
        src.write_text(_BASIC_COMPOSE)

        rewriter = ComposeRewriter()
        rewriter.rewrite(str(src), [_make_rec("web")], str(dst))

        diff_output = rewriter.diff(str(src), str(dst))
        assert "+" in diff_output
        assert "limits" in diff_output or "memory" in diff_output

    def test_diff_no_changes(self, tmp_path: Path) -> None:
        src = tmp_path / "a.yml"
        dst = tmp_path / "b.yml"
        src.write_text("same content\n")
        dst.write_text("same content\n")

        rewriter = ComposeRewriter()
        diff_output = rewriter.diff(str(src), str(dst))
        assert diff_output.strip() == ""

    def test_rewrite_multiple_services(self, tmp_path: Path) -> None:
        compose_multi = """\
version: "3.8"
services:
  web:
    image: nginx:latest
  api:
    image: node:18
  db:
    image: postgres:16
"""
        src = tmp_path / "docker-compose.yml"
        dst = tmp_path / "docker-compose.optimized.yml"
        src.write_text(compose_multi)

        recs = [
            _make_rec("web", mem_limit=128.0, cpu_limit=0.25),
            _make_rec("api", mem_limit=512.0, cpu_limit=1.0),
            _make_rec("db", mem_limit=1024.0, cpu_limit=2.0),
        ]

        rewriter = ComposeRewriter()
        rewriter.rewrite(str(src), recs, str(dst))

        content = dst.read_text()
        assert "128M" in content
        assert "512M" in content
        assert "1024M" in content
