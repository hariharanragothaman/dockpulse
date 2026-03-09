"""Tests for the startup profiler with mocked Docker client."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dockpulse.models import StartupProfile
from dockpulse.startup import StartupProfiler


def _make_mock_client(
    *,
    has_healthcheck: bool = False,
    health_status: str = "healthy",
    image_size: int = 100 * 1024 * 1024,
) -> MagicMock:
    """Build a mock Docker client with configurable behavior."""
    client = MagicMock()

    mock_image = MagicMock()
    mock_image.attrs = {"Size": image_size}
    client.images.get.return_value = mock_image

    mock_container = MagicMock()
    mock_container.status = "running"

    config = {"Healthcheck": {"Test": ["CMD", "true"]}} if has_healthcheck else {}
    health_section = {"Status": health_status} if has_healthcheck else {}

    mock_container.attrs = {
        "Config": config,
        "State": {"Health": health_section} if has_healthcheck else {},
    }

    client.containers.create.return_value = mock_container
    return client


class TestStartupProfiler:
    def test_profile_basic_image(self) -> None:
        client = _make_mock_client()
        profiler = StartupProfiler(client=client)

        result = profiler.profile_startup("nginx:latest", runs=1)

        assert isinstance(result, StartupProfile)
        assert result.container_name == "nginx"
        assert result.image == "nginx:latest"
        assert result.create_to_running_ms >= 0
        assert result.total_startup_ms >= 0
        assert result.has_healthcheck is False
        assert result.running_to_healthy_ms == 0.0

    def test_profile_with_healthcheck(self) -> None:
        client = _make_mock_client(has_healthcheck=True, health_status="healthy")
        profiler = StartupProfiler(client=client)

        result = profiler.profile_startup("myapp:latest", runs=1)

        assert result.has_healthcheck is True
        assert result.total_startup_ms >= result.create_to_running_ms

    def test_profile_multiple_runs_averages(self) -> None:
        client = _make_mock_client()
        profiler = StartupProfiler(client=client)

        result = profiler.profile_startup("nginx:latest", runs=3)

        assert client.containers.create.call_count == 3
        assert result.create_to_running_ms >= 0

    def test_image_size_reported(self) -> None:
        client = _make_mock_client(image_size=200 * 1024 * 1024)
        profiler = StartupProfiler(client=client)

        result = profiler.profile_startup("nginx:latest", runs=1)

        assert result.image_size_mb == pytest.approx(200.0, abs=0.1)

    def test_container_cleanup(self) -> None:
        client = _make_mock_client()
        profiler = StartupProfiler(client=client)
        container = client.containers.create.return_value

        profiler.profile_startup("nginx:latest", runs=1, cleanup=True)

        container.stop.assert_called_once()
        container.remove.assert_called_once_with(force=True)

    def test_no_cleanup_when_disabled(self) -> None:
        client = _make_mock_client()
        profiler = StartupProfiler(client=client)
        container = client.containers.create.return_value

        profiler.profile_startup("nginx:latest", runs=1, cleanup=False)

        container.stop.assert_not_called()
        container.remove.assert_not_called()

    def test_container_name_from_complex_image(self) -> None:
        client = _make_mock_client()
        profiler = StartupProfiler(client=client)

        result = profiler.profile_startup("registry.example.com/myorg/myapp:v2.1", runs=1)

        assert result.container_name == "myapp"

    def test_unhealthy_container(self) -> None:
        client = _make_mock_client(has_healthcheck=True, health_status="unhealthy")
        profiler = StartupProfiler(client=client)

        result = profiler.profile_startup("myapp:latest", runs=1)

        assert result.has_healthcheck is True
        assert result.running_to_healthy_ms == 0.0


class TestComposeStartup:
    def test_profile_compose(self, tmp_path: object) -> None:
        from pathlib import Path

        compose = Path(str(tmp_path)) / "docker-compose.yml"
        compose.write_text(
            "services:\n  web:\n    image: nginx:latest\n  db:\n    image: postgres:16\n"
        )

        client = _make_mock_client()
        profiler = StartupProfiler(client=client)

        results = profiler.profile_compose_startup(str(compose), runs=1)

        assert len(results) == 2
        names = {r.container_name for r in results}
        assert names == {"web", "db"}

    def test_compose_skips_build_only_services(self, tmp_path: object) -> None:
        from pathlib import Path

        compose = Path(str(tmp_path)) / "docker-compose.yml"
        compose.write_text(
            "services:\n  web:\n    image: nginx:latest\n  custom:\n    build: ./custom\n"
        )

        client = _make_mock_client()
        profiler = StartupProfiler(client=client)

        results = profiler.profile_compose_startup(str(compose), runs=1)

        assert len(results) == 1
        assert results[0].container_name == "web"
