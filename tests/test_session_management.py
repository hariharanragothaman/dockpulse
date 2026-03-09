"""Tests for session management (SQLite persistence, listing, deletion)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

from dockpulse.collector import StatsCollector
from dockpulse.models import ContainerStats


def _init_db(db_path: str) -> sqlite3.Connection:
    """Initialise the DB schema using the collector's internal method."""
    return StatsCollector._init_db(db_path)


def _make_stat(
    *,
    name: str = "web",
    offset_seconds: int = 0,
    cpu: float = 25.0,
    mem_mb: float = 200.0,
    mem_limit_mb: float = 512.0,
) -> ContainerStats:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)
    return ContainerStats(
        container_id="abc123",
        name=name,
        timestamp=ts,
        cpu_percent=cpu,
        memory_usage_mb=mem_mb,
        memory_limit_mb=mem_limit_mb,
        memory_percent=(mem_mb / mem_limit_mb * 100) if mem_limit_mb else 0.0,
        network_rx_mb=0.0,
        network_tx_mb=0.0,
        block_read_mb=0.0,
        block_write_mb=0.0,
        pids=5,
    )


def _insert_session(
    conn: sqlite3.Connection,
    session_id: str,
    started_at: str | None = None,
    status: str = "completed",
) -> None:
    if started_at is None:
        started_at = datetime.now(tz=timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO sessions (session_id, started_at, ended_at, duration_seconds, "
        "interval_seconds, container_count, sample_count, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, started_at, started_at, 60, 1.0, 1, 5, status),
    )
    conn.commit()


def _insert_sample(
    conn: sqlite3.Connection,
    session_id: str,
    stat: ContainerStats,
) -> None:
    StatsCollector._persist_sample(conn, stat, session_id)


class TestListSessions:
    """Verify listing profiling sessions."""

    def test_list_sessions_empty(self, tmp_path: Path) -> None:
        db = str(tmp_path / "test.db")
        conn = _init_db(db)
        conn.close()

        sessions = StatsCollector.list_sessions(db)
        assert sessions == []


class TestProfileCreatesSession:
    """Verify that persisting samples creates recoverable sessions."""

    def test_profile_creates_session(self, tmp_path: Path) -> None:
        db = str(tmp_path / "test.db")
        conn = _init_db(db)

        session_id = "test-session-001"
        _insert_session(conn, session_id)
        for i in range(5):
            _insert_sample(conn, session_id, _make_stat(offset_seconds=i))
        conn.close()

        sessions = StatsCollector.list_sessions(db)
        assert len(sessions) == 1
        assert sessions[0].session_id == session_id
        assert sessions[0].status == "completed"


class TestLoadSamples:
    """Verify loading samples from the database."""

    def test_load_samples_latest(self, tmp_path: Path) -> None:
        db = str(tmp_path / "test.db")
        conn = _init_db(db)

        _insert_session(conn, "old-session", started_at="2026-01-01T00:00:00+00:00")
        _insert_sample(conn, "old-session", _make_stat(name="old-web", offset_seconds=0))

        _insert_session(conn, "new-session", started_at="2026-06-01T00:00:00+00:00")
        for i in range(3):
            _insert_sample(conn, "new-session", _make_stat(name="new-web", offset_seconds=i))
        conn.close()

        samples = StatsCollector.load_samples_from_db(db, session_id=None)
        assert "new-web" in samples
        assert "old-web" not in samples
        assert len(samples["new-web"]) == 3


class TestDeleteSession:
    """Verify session and sample deletion."""

    def test_delete_session(self, tmp_path: Path) -> None:
        db = str(tmp_path / "test.db")
        conn = _init_db(db)

        session_id = "delete-me"
        _insert_session(conn, session_id)
        for i in range(3):
            _insert_sample(conn, session_id, _make_stat(offset_seconds=i))
        conn.close()

        assert StatsCollector.delete_session(db, session_id) is True

        sessions = StatsCollector.list_sessions(db)
        assert len(sessions) == 0

        samples = StatsCollector.load_samples_from_db(db, session_id=session_id)
        assert samples == {}
