"""CLI integration tests using typer.testing.CliRunner.

Covers all 14 CLI commands with mocked Docker client and SQLite database.
No Docker daemon required for test execution.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from dockpulse import __version__
from dockpulse.cli import app
from dockpulse.config import Config
from dockpulse.models import StartupProfile

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    """Return path to a temporary database file (not yet created)."""
    return tmp_path / "profiles.db"


@pytest.fixture()
def config_with_db(tmp_db: Path) -> Config:
    """Return a Config pointing at the temporary database."""
    return Config(db_path=str(tmp_db))


@pytest.fixture()
def seeded_db(tmp_db: Path) -> Path:
    """Create a database with sessions table, one session, and sample data."""
    conn = sqlite3.connect(str(tmp_db))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id       TEXT PRIMARY KEY,
            started_at       TEXT,
            ended_at         TEXT,
            duration_seconds INTEGER,
            interval_seconds REAL,
            container_count  INTEGER DEFAULT 0,
            sample_count     INTEGER DEFAULT 0,
            status           TEXT DEFAULT 'running'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS samples (
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
            pids             INTEGER
        )
    """)

    session_id = "abc12345deadbeef"
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ended = started + timedelta(minutes=5)

    conn.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (session_id, started.isoformat(), ended.isoformat(), 300, 1.0, 2, 20, "completed"),
    )

    for i in range(10):
        ts = started + timedelta(seconds=i * 30)
        conn.execute(
            "INSERT INTO samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "ctr1",
                "web-app",
                ts.isoformat(),
                25.0 + i,
                200.0 + i * 5,
                512.0,
                40.0,
                1.0,
                0.5,
                0.2,
                0.1,
                10,
            ),
        )
        conn.execute(
            "INSERT INTO samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "ctr2",
                "redis",
                ts.isoformat(),
                5.0 + i,
                50.0 + i,
                256.0,
                20.0,
                0.1,
                0.05,
                0.01,
                0.005,
                3,
            ),
        )

    conn.commit()
    conn.close()
    return tmp_db


@pytest.fixture()
def seeded_db_two_sessions(tmp_db: Path) -> Path:
    """Database with two sessions for comparison tests."""
    conn = sqlite3.connect(str(tmp_db))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY, started_at TEXT, ended_at TEXT,
            duration_seconds INTEGER, interval_seconds REAL,
            container_count INTEGER DEFAULT 0, sample_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS samples (
            container_id TEXT, name TEXT, timestamp TEXT,
            cpu_percent REAL, memory_usage_mb REAL, memory_limit_mb REAL,
            memory_percent REAL, network_rx_mb REAL, network_tx_mb REAL,
            block_read_mb REAL, block_write_mb REAL, pids INTEGER
        )
    """)

    s1_id = "session1aaa"
    s1_start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    s1_end = s1_start + timedelta(minutes=5)

    s2_id = "session2bbb"
    s2_start = datetime(2026, 1, 2, tzinfo=timezone.utc)
    s2_end = s2_start + timedelta(minutes=5)

    conn.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (s1_id, s1_start.isoformat(), s1_end.isoformat(), 300, 1.0, 1, 5, "completed"),
    )
    conn.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (s2_id, s2_start.isoformat(), s2_end.isoformat(), 300, 1.0, 1, 5, "completed"),
    )

    for i in range(5):
        ts1 = s1_start + timedelta(seconds=i * 30)
        conn.execute(
            "INSERT INTO samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "ctr1",
                "web-app",
                ts1.isoformat(),
                20.0 + i,
                180.0 + i * 5,
                512.0,
                35.0,
                1.0,
                0.5,
                0.2,
                0.1,
                10,
            ),
        )
        ts2 = s2_start + timedelta(seconds=i * 30)
        conn.execute(
            "INSERT INTO samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "ctr1",
                "web-app",
                ts2.isoformat(),
                40.0 + i,
                300.0 + i * 5,
                512.0,
                60.0,
                2.0,
                1.0,
                0.4,
                0.2,
                12,
            ),
        )

    conn.commit()
    conn.close()
    return tmp_db


# ---------------------------------------------------------------------------
# --version
# ---------------------------------------------------------------------------


class TestVersion:
    def test_version_flag(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_short_version_flag(self) -> None:
        result = runner.invoke(app, ["-V"])
        assert result.exit_code == 0
        assert __version__ in result.output


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------


class TestProfile:
    @staticmethod
    def _ensure_samples_table(db_path: Path) -> None:
        """Create the samples table so post-profile queries don't fail."""
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS samples (
                container_id TEXT, name TEXT, timestamp TEXT,
                cpu_percent REAL, memory_usage_mb REAL, memory_limit_mb REAL,
                memory_percent REAL, network_rx_mb REAL, network_tx_mb REAL,
                block_read_mb REAL, block_write_mb REAL, pids INTEGER
            )
        """)
        conn.commit()
        conn.close()

    def test_profile_runs_and_completes(self, tmp_db: Path) -> None:
        mock_collector = MagicMock()
        mock_collector.profile.return_value = None
        self._ensure_samples_table(tmp_db)

        with (
            patch("dockpulse.cli._config", Config(db_path=str(tmp_db))),
            patch("dockpulse.cli.StatsCollector", return_value=mock_collector),
        ):
            result = runner.invoke(app, ["profile", "-d", "5s", "-q"])

        assert result.exit_code == 0
        mock_collector.profile.assert_called_once()

    def test_profile_creates_session_in_db(self, tmp_db: Path) -> None:
        mock_collector = MagicMock()
        mock_collector.profile.return_value = None
        self._ensure_samples_table(tmp_db)

        with (
            patch("dockpulse.cli._config", Config(db_path=str(tmp_db))),
            patch("dockpulse.cli.StatsCollector", return_value=mock_collector),
        ):
            result = runner.invoke(app, ["profile", "-d", "5s", "-q"])

        assert result.exit_code == 0

        conn = sqlite3.connect(str(tmp_db))
        rows = conn.execute("SELECT * FROM sessions").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][7] == "completed"

    def test_profile_with_containers_flag(self, tmp_db: Path) -> None:
        mock_collector = MagicMock()
        mock_collector.profile.return_value = None
        self._ensure_samples_table(tmp_db)

        with (
            patch("dockpulse.cli._config", Config(db_path=str(tmp_db))),
            patch("dockpulse.cli.StatsCollector", return_value=mock_collector),
        ):
            result = runner.invoke(app, ["profile", "-d", "5s", "-q", "-c", "web,redis"])

        assert result.exit_code == 0
        call_kwargs = mock_collector.profile.call_args[1]
        assert call_kwargs["container_ids"] == ["web", "redis"]


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


class TestAnalyze:
    def test_analyze_no_db(self, tmp_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(tmp_db))):
            result = runner.invoke(app, ["analyze"])

        assert result.exit_code == 1
        assert "No profile data found" in result.output

    def test_analyze_empty_db(self, tmp_db: Path) -> None:
        conn = sqlite3.connect(str(tmp_db))
        conn.execute("""
            CREATE TABLE samples (
                container_id TEXT, name TEXT, timestamp TEXT,
                cpu_percent REAL, memory_usage_mb REAL, memory_limit_mb REAL,
                memory_percent REAL, network_rx_mb REAL, network_tx_mb REAL,
                block_read_mb REAL, block_write_mb REAL, pids INTEGER
            )
        """)
        conn.commit()
        conn.close()

        with patch("dockpulse.cli._config", Config(db_path=str(tmp_db))):
            result = runner.invoke(app, ["analyze"])

        assert result.exit_code == 1
        assert "empty" in result.output

    def test_analyze_rich_format(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["analyze"])

        assert result.exit_code == 0

    def test_analyze_json_requires_output(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["analyze", "-f", "json"])

        assert result.exit_code == 1
        assert "--output is required" in result.output

    def test_analyze_json_format(self, seeded_db: Path, tmp_path: Path) -> None:
        out = str(tmp_path / "report.json")
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["analyze", "-f", "json", "-o", out])

        assert result.exit_code == 0
        assert Path(out).exists()

    def test_analyze_html_requires_output(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["analyze", "-f", "html"])

        assert result.exit_code == 1
        assert "--output is required" in result.output

    def test_analyze_html_format(self, seeded_db: Path, tmp_path: Path) -> None:
        out = str(tmp_path / "report.html")
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["analyze", "-f", "html", "-o", out])

        assert result.exit_code == 0
        assert Path(out).exists()


# ---------------------------------------------------------------------------
# right-size
# ---------------------------------------------------------------------------


class TestRightSize:
    def test_right_size_no_db(self, tmp_db: Path, tmp_path: Path) -> None:
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("services:\n  web:\n    image: nginx\n")

        with patch("dockpulse.cli._config", Config(db_path=str(tmp_db))):
            result = runner.invoke(app, ["right-size", str(compose)])

        assert result.exit_code == 1
        assert "No profile data found" in result.output

    def test_right_size_success(self, seeded_db: Path, tmp_path: Path) -> None:
        compose = tmp_path / "docker-compose.yml"
        compose.write_text(
            "services:\n  web-app:\n    image: nginx\n    deploy:\n"
            "      resources:\n        limits:\n          memory: 512M\n          cpus: '1.0'\n"
        )

        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["right-size", str(compose)])

        assert result.exit_code == 0
        assert "Optimised" in result.output or "optimized" in result.output.lower()


# ---------------------------------------------------------------------------
# dashboard
# ---------------------------------------------------------------------------


class TestDashboard:
    def test_dashboard_keyboard_interrupt(self) -> None:
        mock_collector = MagicMock()
        mock_collector.collect_all.side_effect = KeyboardInterrupt

        with patch("dockpulse.cli.StatsCollector", return_value=mock_collector):
            result = runner.invoke(app, ["dashboard"])

        assert result.exit_code == 0
        assert "Dashboard stopped" in result.output or "dashboard" in result.output.lower()


# ---------------------------------------------------------------------------
# waste
# ---------------------------------------------------------------------------


class TestWaste:
    def test_waste_no_db(self, tmp_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(tmp_db))):
            result = runner.invoke(app, ["waste"])

        assert result.exit_code == 1
        assert "No profile data found" in result.output

    def test_waste_with_data(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["waste"])

        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


class TestReport:
    def test_report_no_db(self, tmp_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(tmp_db))):
            result = runner.invoke(app, ["report"])

        assert result.exit_code == 1
        assert "No profile data found" in result.output

    def test_report_profile_type(self, seeded_db: Path, tmp_path: Path) -> None:
        out = str(tmp_path / "report.html")
        mock_viz = MagicMock()
        mock_viz.generate_profile_report.return_value = None

        with (
            patch("dockpulse.cli._config", Config(db_path=str(seeded_db))),
            patch("dockpulse.cli.Visualizer", return_value=mock_viz),
        ):
            result = runner.invoke(app, ["report", "-t", "profile", "-o", out])

        assert result.exit_code == 0
        mock_viz.generate_profile_report.assert_called_once()

    def test_report_comparison_missing_sessions(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["report", "-t", "comparison"])

        assert result.exit_code == 1
        assert "--session-a" in result.output

    def test_report_invalid_type(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["report", "-t", "invalid"])

        assert result.exit_code == 1
        assert "Unknown report type" in result.output

    def test_report_stack_type(self, seeded_db: Path, tmp_path: Path) -> None:
        out = str(tmp_path / "stack.html")
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["report", "-t", "stack", "-o", out])

        assert result.exit_code == 0
        assert Path(out).exists()


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------


class TestSessions:
    def test_sessions_no_db(self, tmp_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(tmp_db))):
            result = runner.invoke(app, ["sessions"])

        assert result.exit_code == 1
        assert "No profile data found" in result.output

    def test_sessions_no_table(self, tmp_db: Path) -> None:
        conn = sqlite3.connect(str(tmp_db))
        conn.execute("CREATE TABLE samples (container_id TEXT)")
        conn.commit()
        conn.close()

        with patch("dockpulse.cli._config", Config(db_path=str(tmp_db))):
            result = runner.invoke(app, ["sessions"])

        assert result.exit_code == 1
        assert "No sessions table" in result.output

    def test_sessions_empty_table(self, tmp_db: Path) -> None:
        conn = sqlite3.connect(str(tmp_db))
        conn.execute("""
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY, started_at TEXT, ended_at TEXT,
                duration_seconds INTEGER, interval_seconds REAL,
                container_count INTEGER DEFAULT 0, sample_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running'
            )
        """)
        conn.commit()
        conn.close()

        with patch("dockpulse.cli._config", Config(db_path=str(tmp_db))):
            result = runner.invoke(app, ["sessions"])

        assert result.exit_code == 0
        assert "No sessions recorded" in result.output

    def test_sessions_lists_data(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["sessions"])

        assert result.exit_code == 0
        assert "abc12345" in result.output


# ---------------------------------------------------------------------------
# compare
# ---------------------------------------------------------------------------


class TestCompare:
    def test_compare_no_db(self, tmp_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(tmp_db))):
            result = runner.invoke(app, ["compare", "aaa", "bbb"])

        assert result.exit_code == 1
        assert "No profile data found" in result.output

    def test_compare_invalid_session(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["compare", "nonexist1", "nonexist2"])

        assert result.exit_code == 1
        assert "No session matching" in result.output

    def test_compare_success(self, seeded_db_two_sessions: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db_two_sessions))):
            result = runner.invoke(app, ["compare", "session1", "session2"])

        assert result.exit_code == 0
        assert "web-app" in result.output


# ---------------------------------------------------------------------------
# stack
# ---------------------------------------------------------------------------


class TestStack:
    def test_stack_no_db(self, tmp_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(tmp_db))):
            result = runner.invoke(app, ["stack"])

        assert result.exit_code == 1
        assert "No profile data found" in result.output

    def test_stack_rich_format(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["stack"])

        assert result.exit_code == 0
        assert "Stack Analysis" in result.output

    def test_stack_json_format(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["stack", "-f", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "bottleneck" in data
        assert "service_rankings" in data

    def test_stack_with_compose(self, seeded_db: Path, tmp_path: Path) -> None:
        compose = tmp_path / "docker-compose.yml"
        compose.write_text(
            "services:\n"
            "  web-app:\n"
            "    image: nginx\n"
            "    depends_on:\n"
            "      - redis\n"
            "  redis:\n"
            "    image: redis\n"
        )

        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["stack", str(compose)])

        assert result.exit_code == 0
        assert "Dependencies" in result.output

    def test_stack_compose_not_found(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["stack", "/nonexistent/compose.yml"])

        assert result.exit_code == 1
        assert "not found" in result.output


# ---------------------------------------------------------------------------
# clean
# ---------------------------------------------------------------------------


class TestClean:
    def test_clean_no_db(self, tmp_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(tmp_db))):
            result = runner.invoke(app, ["clean"])

        assert result.exit_code == 0
        assert "Nothing to clean" in result.output

    def test_clean_all(self, seeded_db: Path) -> None:
        assert seeded_db.exists()

        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["clean", "--all"])

        assert result.exit_code == 0
        assert "deleted" in result.output.lower()
        assert not seeded_db.exists()

    def test_clean_specific_session(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["clean", "-s", "abc12345"])

        assert result.exit_code == 0
        assert "deleted" in result.output.lower()

    def test_clean_session_not_found(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["clean", "-s", "nonexistent"])

        assert result.exit_code == 1
        assert "No session matching" in result.output

    def test_clean_no_flags_shows_help(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["clean"])

        assert result.exit_code == 0
        assert "--all" in result.output or "--session" in result.output


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


class TestExport:
    def test_export_starts_and_stops(self) -> None:
        mock_exporter = MagicMock()
        mock_exporter.start.return_value = None
        mock_exporter.stop.return_value = None

        with (
            patch(
                "dockpulse.prometheus.PrometheusExporter", return_value=mock_exporter
            ) as mock_cls,
            patch("threading.Event") as mock_event,
        ):
            mock_event.return_value.wait.side_effect = KeyboardInterrupt
            result = runner.invoke(app, ["export", "-p", "9091"])

        assert result.exit_code == 0
        mock_cls.assert_called_once_with(port=9091)
        mock_exporter.start.assert_called_once()
        mock_exporter.stop.assert_called_once()


# ---------------------------------------------------------------------------
# cost
# ---------------------------------------------------------------------------


class TestCost:
    def test_cost_no_db(self, tmp_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(tmp_db))):
            result = runner.invoke(app, ["cost"])

        assert result.exit_code == 1
        assert "No profile data found" in result.output

    def test_cost_rich_format(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["cost"])

        assert result.exit_code == 0
        assert "$" in result.output

    def test_cost_json_format(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["cost", "-f", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "provider" in data
        assert "total_current_cost" in data

    def test_cost_gcp_provider(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["cost", "-p", "gcp"])

        assert result.exit_code == 0
        assert "$" in result.output

    def test_cost_azure_provider(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["cost", "-p", "azure"])

        assert result.exit_code == 0
        assert "$" in result.output

    def test_cost_invalid_provider(self, seeded_db: Path) -> None:
        with patch("dockpulse.cli._config", Config(db_path=str(seeded_db))):
            result = runner.invoke(app, ["cost", "-p", "invalid_cloud"])

        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# startup
# ---------------------------------------------------------------------------


class TestStartup:
    def test_startup_no_args(self) -> None:
        result = runner.invoke(app, ["startup"])
        assert result.exit_code == 1
        assert "Provide an image name" in result.output

    def test_startup_with_image(self) -> None:
        mock_profiler = MagicMock()
        mock_profiler.profile_startup.return_value = StartupProfile(
            container_name="nginx",
            image="nginx:latest",
            create_to_running_ms=500.0,
            running_to_healthy_ms=0.0,
            total_startup_ms=500.0,
            image_size_mb=142.0,
            has_healthcheck=False,
        )

        with patch("dockpulse.startup.StartupProfiler", return_value=mock_profiler):
            result = runner.invoke(app, ["startup", "nginx:latest"])

        assert result.exit_code == 0
        assert "nginx" in result.output
        mock_profiler.profile_startup.assert_called_once_with("nginx:latest", runs=3)

    def test_startup_json_format(self) -> None:
        mock_profiler = MagicMock()
        mock_profiler.profile_startup.return_value = StartupProfile(
            container_name="nginx",
            image="nginx:latest",
            create_to_running_ms=500.0,
            running_to_healthy_ms=0.0,
            total_startup_ms=500.0,
            image_size_mb=142.0,
            has_healthcheck=False,
        )

        with patch("dockpulse.startup.StartupProfiler", return_value=mock_profiler):
            result = runner.invoke(app, ["startup", "nginx:latest", "-f", "json"])

        assert result.exit_code == 0
        # Output includes a "Profiling..." line before the JSON array
        json_start = result.output.find("[")
        assert json_start != -1
        data = json.loads(result.output[json_start:])
        assert data[0]["image"] == "nginx:latest"

    def test_startup_with_compose(self, tmp_path: Path) -> None:
        compose = tmp_path / "docker-compose.yml"
        compose.write_text("services:\n  web:\n    image: nginx\n  redis:\n    image: redis\n")

        mock_profiler = MagicMock()
        mock_profiler.profile_compose_startup.return_value = [
            StartupProfile(
                container_name="web",
                image="nginx",
                create_to_running_ms=500.0,
                running_to_healthy_ms=0.0,
                total_startup_ms=500.0,
                image_size_mb=142.0,
                has_healthcheck=False,
            ),
            StartupProfile(
                container_name="redis",
                image="redis",
                create_to_running_ms=300.0,
                running_to_healthy_ms=0.0,
                total_startup_ms=300.0,
                image_size_mb=40.0,
                has_healthcheck=False,
            ),
        ]

        with patch("dockpulse.startup.StartupProfiler", return_value=mock_profiler):
            result = runner.invoke(app, ["startup", "--compose", str(compose)])

        assert result.exit_code == 0
        assert "web" in result.output
        assert "redis" in result.output

    def test_startup_custom_runs(self) -> None:
        mock_profiler = MagicMock()
        mock_profiler.profile_startup.return_value = StartupProfile(
            container_name="nginx",
            image="nginx:latest",
            create_to_running_ms=500.0,
            running_to_healthy_ms=0.0,
            total_startup_ms=500.0,
            image_size_mb=142.0,
            has_healthcheck=False,
        )

        with patch("dockpulse.startup.StartupProfiler", return_value=mock_profiler):
            result = runner.invoke(app, ["startup", "nginx:latest", "-n", "5"])

        assert result.exit_code == 0
        mock_profiler.profile_startup.assert_called_once_with("nginx:latest", runs=5)
