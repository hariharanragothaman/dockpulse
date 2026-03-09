"""Container startup time profiling."""

from __future__ import annotations

import contextlib
import time
from typing import Any

import docker
from docker.errors import APIError, ImageNotFound

from dockpulse.models import StartupProfile

_POLL_INTERVAL_S = 0.05
_HEALTHY_TIMEOUT_S = 120.0


class StartupProfiler:
    """Measures container startup times including create -> running -> healthy."""

    def __init__(self, client: Any | None = None) -> None:
        self._client: Any = client or docker.from_env()

    def profile_startup(
        self,
        image: str,
        command: str | None = None,
        *,
        environment: dict[str, str] | None = None,
        runs: int = 3,
        cleanup: bool = True,
    ) -> StartupProfile:
        """Profile startup time for a given image, averaged over multiple runs."""
        create_times: list[float] = []
        healthy_times: list[float] = []
        total_times: list[float] = []
        image_size_mb = 0.0
        has_healthcheck = False

        try:
            img = self._client.images.get(image)
            image_size_mb = (img.attrs.get("Size", 0) or 0) / (1024 * 1024)
        except ImageNotFound:
            try:
                self._client.images.pull(image)
                img = self._client.images.get(image)
                image_size_mb = (img.attrs.get("Size", 0) or 0) / (1024 * 1024)
            except APIError:
                pass

        for _ in range(runs):
            result = self._single_run(image, command, environment, cleanup)
            create_times.append(result["create_to_running_ms"])
            healthy_times.append(result["running_to_healthy_ms"])
            total_times.append(result["total_startup_ms"])
            has_healthcheck = result["has_healthcheck"]

        avg = lambda lst: sum(lst) / len(lst) if lst else 0.0  # noqa: E731

        return StartupProfile(
            container_name=image.split("/")[-1].split(":")[0],
            image=image,
            create_to_running_ms=round(avg(create_times), 2),
            running_to_healthy_ms=round(avg(healthy_times), 2),
            total_startup_ms=round(avg(total_times), 2),
            image_size_mb=round(image_size_mb, 2),
            has_healthcheck=has_healthcheck,
        )

    def _single_run(
        self,
        image: str,
        command: str | None,
        environment: dict[str, str] | None,
        cleanup: bool,
    ) -> dict[str, Any]:
        t_create = time.perf_counter()
        container = self._client.containers.create(
            image,
            command=command,
            environment=environment,
            detach=True,
        )

        try:
            container.start()
            time.perf_counter()

            container.reload()
            while container.status != "running":
                time.sleep(_POLL_INTERVAL_S)
                container.reload()
            t_running = time.perf_counter()

            create_to_running_ms = (t_running - t_create) * 1000

            has_healthcheck = bool(container.attrs.get("Config", {}).get("Healthcheck"))

            running_to_healthy_ms = 0.0
            if has_healthcheck:
                deadline = time.perf_counter() + _HEALTHY_TIMEOUT_S
                while time.perf_counter() < deadline:
                    container.reload()
                    health = container.attrs.get("State", {}).get("Health", {}).get("Status", "")
                    if health == "healthy":
                        running_to_healthy_ms = (time.perf_counter() - t_running) * 1000
                        break
                    if health == "unhealthy":
                        break
                    time.sleep(_POLL_INTERVAL_S)

            total_ms = create_to_running_ms + running_to_healthy_ms

            return {
                "create_to_running_ms": create_to_running_ms,
                "running_to_healthy_ms": running_to_healthy_ms,
                "total_startup_ms": total_ms,
                "has_healthcheck": has_healthcheck,
            }
        finally:
            if cleanup:
                with contextlib.suppress(Exception):
                    container.stop(timeout=5)
                with contextlib.suppress(Exception):
                    container.remove(force=True)

    def profile_compose_startup(
        self,
        compose_path: str,
        *,
        runs: int = 3,
    ) -> list[StartupProfile]:
        """Profile startup time for each service defined in a compose file."""
        from pathlib import Path

        from ruamel.yaml import YAML

        yaml = YAML()
        doc = yaml.load(Path(compose_path))
        services = doc.get("services", {})

        results: list[StartupProfile] = []
        for svc_name, svc_cfg in services.items():
            image = svc_cfg.get("image")
            if not image:
                continue
            command = svc_cfg.get("command")
            env_list = svc_cfg.get("environment", {})
            env = dict(env_list) if isinstance(env_list, dict) else {}

            profile = self.profile_startup(
                image=image,
                command=command,
                environment=env,
                runs=runs,
            )
            results.append(
                StartupProfile(
                    container_name=svc_name,
                    image=profile.image,
                    create_to_running_ms=profile.create_to_running_ms,
                    running_to_healthy_ms=profile.running_to_healthy_ms,
                    total_startup_ms=profile.total_startup_ms,
                    image_size_mb=profile.image_size_mb,
                    has_healthcheck=profile.has_healthcheck,
                )
            )

        return results
