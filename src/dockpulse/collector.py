"""Stats collector that streams container resource data from the Docker API."""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import docker
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn, TimeRemainingColumn

from dockpulse.models import ContainerStats, ProfileSession

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
    return float(round((cpu_delta / system_delta) * online_cpus * 100.0, 2))


def _parse_network_io(stats: dict[str, Any]) -> tuple[float, float]:
    """Sum network bytes across all interfaces."""
    networks = stats.get("networks", {})
    rx = sum(iface.get("rx_bytes", 0) for iface in networks.values())
    tx = sum(iface.get("tx_bytes", 0) for iface in networks.values())
    return _bytes_to_mb(rx), _bytes_to_mb(tx)


def _parse_block_io(stats: dict[str, Any]) -> tuple[float, float]:
    """Extract read and write bytes from blkio stats."""
    entries = stats.get("blkio_stats", {}).get("io_service_bytes_recursive") or []
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
        session_id = str(uuid.uuid4())
        conn = self._init_db(db_path) if db_path else None

        if conn:
            self._create_session(
                conn,
                session_id=session_id,
                duration_seconds=duration_seconds,
                interval=interval,
            )

        samples: dict[str, list[ContainerStats]] = {}
        deadline = time.monotonic() + duration_seconds
        total_samples = 0
        container_names: set[str] = set()
        status = "completed"

        progress = Progress(
            TextColumn("[bold blue]Profiling"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            TextColumn("/"),
            TimeRemainingColumn(),
            TextColumn("•"),
            TextColumn("[cyan]{task.fields[samples]} samples"),
            TextColumn("•"),
            TextColumn("[green]{task.fields[containers]} containers"),
            transient=True,
        )

        try:
            with progress:
                task = progress.add_task(
                    "profiling",
                    total=duration_seconds,
                    samples=0,
                    containers=0,
                )

                while time.monotonic() < deadline:
                    tick_start = time.monotonic()

                    targets = container_ids or [c.id for c in self._client.containers.list()]

                    for cid in targets:
                        try:
                            stat = self.collect_stats(cid)
                        except Exception:
                            continue

                        samples.setdefault(stat.name, []).append(stat)
                        total_samples += 1
                        container_names.add(stat.name)

                        if callback:
                            callback(stat)

                        if conn:
                            self._persist_sample(conn, stat, session_id)

                    elapsed_total = duration_seconds - (deadline - time.monotonic())
                    progress.update(
                        task,
                        completed=min(elapsed_total, duration_seconds),
                        samples=total_samples,
                        containers=len(container_names),
                    )

                    elapsed = time.monotonic() - tick_start
                    sleep_time = max(0.0, interval - elapsed)
                    if sleep_time and time.monotonic() < deadline:
                        time.sleep(sleep_time)
        except KeyboardInterrupt:
            status = "interrupted"
        finally:
            if conn:
                self._finish_session(conn, session_id, status, total_samples, len(container_names))
                conn.close()

        return samples

    @staticmethod
    def _init_db(db_path: str) -> sqlite3.Connection:
        """Initialise the SQLite database for sample storage."""
        from pathlib import Path

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id       TEXT PRIMARY KEY,
                started_at       TEXT NOT NULL,
                ended_at         TEXT,
                duration_seconds INTEGER NOT NULL,
                interval_seconds REAL NOT NULL,
                container_count  INTEGER NOT NULL DEFAULT 0,
                sample_count     INTEGER NOT NULL DEFAULT 0,
                status           TEXT NOT NULL DEFAULT 'running'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS samples (
                session_id       TEXT,
                container_id     TEXT,
                name             TEXT,
                timestamp        TEXT,
                cpu_percent      REAL,
                memory_usage_mb  REAL,
                memory_limit_mb  REAL,
                memory_percent   REAL,
                network_rx_mb    REAL,
                network_tx_mb    REAL,
                block_read_mb    REAL,
                block_write_mb   REAL,
                pids             INTEGER,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_samples_session
            ON samples (session_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_samples_name_ts
            ON samples (name, timestamp)
        """)
        conn.commit()
        return conn

    @staticmethod
    def _create_session(
        conn: sqlite3.Connection,
        session_id: str,
        duration_seconds: int,
        interval: float,
    ) -> None:
        conn.execute(
            "INSERT INTO sessions (session_id, started_at, duration_seconds, interval_seconds) "
            "VALUES (?, ?, ?, ?)",
            (session_id, datetime.now(tz=timezone.utc).isoformat(), duration_seconds, interval),
        )
        conn.commit()

    @staticmethod
    def _finish_session(
        conn: sqlite3.Connection,
        session_id: str,
        status: str,
        sample_count: int,
        container_count: int,
    ) -> None:
        conn.execute(
            "UPDATE sessions SET ended_at = ?, status = ?, sample_count = ?, container_count = ? "
            "WHERE session_id = ?",
            (
                datetime.now(tz=timezone.utc).isoformat(),
                status,
                sample_count,
                container_count,
                session_id,
            ),
        )
        conn.commit()

    @staticmethod
    def _persist_sample(
        conn: sqlite3.Connection,
        stat: ContainerStats,
        session_id: str | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
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

    @classmethod
    def load_samples_from_db(
        cls,
        db_path: str,
        session_id: str | None = None,
    ) -> dict[str, list[ContainerStats]]:
        """Load samples from the database, optionally filtering by session.

        If session_id is None, loads the most recent session.
        Returns a dict of container_name -> list[ContainerStats].
        """
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            if session_id is None:
                row = conn.execute(
                    "SELECT session_id FROM sessions ORDER BY started_at DESC LIMIT 1"
                ).fetchone()
                if row is None:
                    return {}
                session_id = row["session_id"]

            rows = conn.execute(
                "SELECT * FROM samples WHERE session_id = ? ORDER BY timestamp",
                (session_id,),
            ).fetchall()

            result: dict[str, list[ContainerStats]] = defaultdict(list)
            for r in rows:
                stat = ContainerStats(
                    container_id=r["container_id"],
                    name=r["name"],
                    timestamp=datetime.fromisoformat(r["timestamp"]),
                    cpu_percent=r["cpu_percent"],
                    memory_usage_mb=r["memory_usage_mb"],
                    memory_limit_mb=r["memory_limit_mb"],
                    memory_percent=r["memory_percent"],
                    network_rx_mb=r["network_rx_mb"],
                    network_tx_mb=r["network_tx_mb"],
                    block_read_mb=r["block_read_mb"],
                    block_write_mb=r["block_write_mb"],
                    pids=r["pids"],
                )
                result[stat.name].append(stat)

            return dict(result)
        finally:
            conn.close()

    @classmethod
    def list_sessions(cls, db_path: str) -> list[ProfileSession]:
        """List all profiling sessions in the database."""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT * FROM sessions ORDER BY started_at DESC").fetchall()

            sessions: list[ProfileSession] = []
            for r in rows:
                ended_at = datetime.fromisoformat(r["ended_at"]) if r["ended_at"] else None
                sessions.append(
                    ProfileSession(
                        session_id=r["session_id"],
                        started_at=datetime.fromisoformat(r["started_at"]),
                        ended_at=ended_at,
                        duration_seconds=r["duration_seconds"],
                        interval_seconds=r["interval_seconds"],
                        container_count=r["container_count"],
                        sample_count=r["sample_count"],
                        status=r["status"],
                    )
                )
            return sessions
        finally:
            conn.close()

    @classmethod
    def delete_session(cls, db_path: str, session_id: str) -> bool:
        """Delete a session and all its samples.

        Returns True if the session existed and was deleted.
        """
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("DELETE FROM samples WHERE session_id = ?", (session_id,))
            deleted = conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.commit()
            return deleted.rowcount > 0
        finally:
            conn.close()
