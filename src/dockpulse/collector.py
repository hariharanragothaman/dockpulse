"""Stats collector that streams container resource data from the Docker API."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import docker

from dockpulse.models import ContainerStats

if TYPE_CHECKING:
    from collections.abc import Callable

    from docker import DockerClient
    from docker.models.containers import Container


def _bytes_to_mb(b: float) -> float:
    return round(b / (1024 * 1024), 2)


def _calculate_cpu_percent(stats: dict[str, Any]) -> float:
    """Calculate CPU usage percentage from Docker stats API response.

    Docker returns cumulative CPU counters; the percentage is derived from the
    delta between the current and previous readings, normalised by the number
    of available CPUs.
    """
    cpu = stats.get("cpu_stats", {})
    precpu = stats.get("precpu_stats", {})

    cpu_total = cpu.get("cpu_usage", {}).get("total_usage", 0)
    precpu_total = precpu.get("cpu_usage", {}).get("total_usage", 0)
    cpu_delta = cpu_total - precpu_total

    system_total = cpu.get("system_cpu_usage", 0)
    presystem_total = precpu.get("system_cpu_usage", 0)
    system_delta = system_total - presystem_total

    if system_delta <= 0 or cpu_delta < 0:
        return 0.0

    online_cpus = cpu.get("online_cpus") or len(cpu.get("cpu_usage", {}).get("percpu_usage", [1]))
    return round((cpu_delta / system_delta) * online_cpus * 100.0, 2)


def _parse_network_io(stats: dict[str, Any]) -> tuple[float, float]:
    """Sum network bytes across all interfaces."""
    networks = stats.get("networks", {})
    rx = sum(iface.get("rx_bytes", 0) for iface in networks.values())
    tx = sum(iface.get("tx_bytes", 0) for iface in networks.values())
    return _bytes_to_mb(rx), _bytes_to_mb(tx)


def _parse_block_io(stats: dict[str, Any]) -> tuple[float, float]:
    """Extract read and write bytes from blkio stats."""
    entries = (
        stats.get("blkio_stats", {}).get("io_service_bytes_recursive") or []
    )
    read = sum(e.get("value", 0) for e in entries if e.get("op", "").lower() == "read")
    write = sum(e.get("value", 0) for e in entries if e.get("op", "").lower() == "write")
    return _bytes_to_mb(read), _bytes_to_mb(write)


def parse_stats(container_id: str, name: str, raw: dict[str, Any]) -> ContainerStats:
    """Convert a raw Docker stats API response into a ``ContainerStats`` instance."""
    memory = raw.get("memory_stats", {})
    mem_usage = memory.get("usage", 0)
    mem_limit = memory.get("limit", 0)
    mem_percent = (mem_usage / mem_limit * 100.0) if mem_limit else 0.0

    rx_mb, tx_mb = _parse_network_io(raw)
    read_mb, write_mb = _parse_block_io(raw)

    return ContainerStats(
        container_id=container_id,
        name=name,
        timestamp=datetime.now(tz=timezone.utc),
        cpu_percent=_calculate_cpu_percent(raw),
        memory_usage_mb=_bytes_to_mb(mem_usage),
        memory_limit_mb=_bytes_to_mb(mem_limit),
        memory_percent=round(mem_percent, 2),
        network_rx_mb=rx_mb,
        network_tx_mb=tx_mb,
        block_read_mb=read_mb,
        block_write_mb=write_mb,
        pids=raw.get("pids_stats", {}).get("current", 0),
    )


class StatsCollector:
    """Collects resource statistics from running Docker containers."""

    def __init__(self, docker_client: DockerClient | None = None) -> None:
        self._client = docker_client or docker.from_env()

    def collect_stats(self, container_id: str) -> ContainerStats:
        """Collect a single stats snapshot for a container.

        Args:
            container_id: Container ID or name.

        Returns:
            A populated ``ContainerStats`` instance.
        """
        container: Container = self._client.containers.get(container_id)
        raw = container.stats(stream=False)
        return parse_stats(
            container_id=container.id,
            name=container.name,
            raw=raw,
        )

    def collect_all(self) -> list[ContainerStats]:
        """Collect a single stats snapshot for every running container."""
        containers: list[Container] = self._client.containers.list()
        results: list[ContainerStats] = []
        for container in containers:
            try:
                raw = container.stats(stream=False)
                results.append(
                    parse_stats(
                        container_id=container.id,
                        name=container.name,
                        raw=raw,
                    )
                )
            except Exception:
                # Container may have stopped between listing and stats call
                continue
        return results

    def profile(
        self,
        container_ids: list[str] | None = None,
        duration_seconds: int = 3600,
        interval: float = 1.0,
        callback: Callable[[ContainerStats], None] | None = None,
        db_path: str | None = None,
    ) -> dict[str, list[ContainerStats]]:
        """Profile containers over a time window, persisting to SQLite.

        Args:
            container_ids: Specific container IDs/names to profile. ``None``
                profiles all running containers.
            duration_seconds: How long to collect samples.
            interval: Seconds between samples.
            callback: Optional function called with each ``ContainerStats``.
            db_path: Optional SQLite path to persist samples.

        Returns:
            Mapping of container name to its collected samples.
        """
        conn = self._init_db(db_path) if db_path else None
        samples: dict[str, list[ContainerStats]] = {}
        deadline = time.monotonic() + duration_seconds

        try:
            while time.monotonic() < deadline:
                tick_start = time.monotonic()

                targets = container_ids or [c.id for c in self._client.containers.list()]

                for cid in targets:
                    try:
                        stat = self.collect_stats(cid)
                    except Exception:
                        continue

                    samples.setdefault(stat.name, []).append(stat)

                    if callback:
                        callback(stat)

                    if conn:
                        self._persist_sample(conn, stat)

                elapsed = time.monotonic() - tick_start
                sleep_time = max(0.0, interval - elapsed)
                if sleep_time and time.monotonic() < deadline:
                    time.sleep(sleep_time)
        finally:
            if conn:
                conn.close()

        return samples

    @staticmethod
    def _init_db(db_path: str) -> sqlite3.Connection:
        """Initialise the SQLite database for sample storage."""
        from pathlib import Path

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS samples (
                container_id   TEXT,
                name           TEXT,
                timestamp      TEXT,
                cpu_percent    REAL,
                memory_usage_mb REAL,
                memory_limit_mb REAL,
                memory_percent REAL,
                network_rx_mb  REAL,
                network_tx_mb  REAL,
                block_read_mb  REAL,
                block_write_mb REAL,
                pids           INTEGER
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_samples_name_ts
            ON samples (name, timestamp)
        """)
        conn.commit()
        return conn

    @staticmethod
    def _persist_sample(conn: sqlite3.Connection, stat: ContainerStats) -> None:
        conn.execute(
            """
            INSERT INTO samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                stat.container_id,
                stat.name,
                stat.timestamp.isoformat(),
                stat.cpu_percent,
                stat.memory_usage_mb,
                stat.memory_limit_mb,
                stat.memory_percent,
                stat.network_rx_mb,
                stat.network_tx_mb,
                stat.block_read_mb,
                stat.block_write_mb,
                stat.pids,
            ),
        )
        conn.commit()
