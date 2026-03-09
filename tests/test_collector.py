"""Tests for the stats collector and Docker stats parsing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dockpulse.collector import StatsCollector, parse_stats


def _make_raw_stats(
    *,
    cpu_total: int = 500_000_000,
    precpu_total: int = 400_000_000,
    system_cpu: int = 10_000_000_000,
    presystem_cpu: int = 9_000_000_000,
    online_cpus: int = 4,
    mem_usage: int = 200 * 1024 * 1024,
    mem_limit: int = 512 * 1024 * 1024,
    rx_bytes: int = 1_048_576,
    tx_bytes: int = 524_288,
    blkio_read: int = 10_485_760,
    blkio_write: int = 5_242_880,
    pids: int = 12,
) -> dict:
    """Build a synthetic Docker stats API response."""
    return {
        "cpu_stats": {
            "cpu_usage": {"total_usage": cpu_total, "percpu_usage": [0] * online_cpus},
            "system_cpu_usage": system_cpu,
            "online_cpus": online_cpus,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": precpu_total, "percpu_usage": [0] * online_cpus},
            "system_cpu_usage": presystem_cpu,
        },
        "memory_stats": {
            "usage": mem_usage,
            "limit": mem_limit,
        },
        "networks": {
            "eth0": {"rx_bytes": rx_bytes, "tx_bytes": tx_bytes},
        },
        "blkio_stats": {
            "io_service_bytes_recursive": [
                {"op": "read", "value": blkio_read},
                {"op": "write", "value": blkio_write},
            ],
        },
        "pids_stats": {"current": pids},
    }


class TestParseDockerStats:
    """Verify that raw Docker stats JSON is correctly parsed into ContainerStats."""

    def test_cpu_percent_calculation(self) -> None:
        raw = _make_raw_stats()
        stat = parse_stats("abc123", "web", raw)

        # CPU delta = 100_000_000, system delta = 1_000_000_000, cpus = 4
        # expected = (100_000_000 / 1_000_000_000) * 4 * 100 = 40.0
        assert stat.cpu_percent == 40.0

    def test_memory_fields(self) -> None:
        raw = _make_raw_stats(mem_usage=256 * 1024 * 1024, mem_limit=1024 * 1024 * 1024)
        stat = parse_stats("abc123", "web", raw)

        assert stat.memory_usage_mb == 256.0
        assert stat.memory_limit_mb == 1024.0
        assert stat.memory_percent == pytest.approx(25.0, abs=0.1)

    def test_network_io(self) -> None:
        raw = _make_raw_stats(rx_bytes=2 * 1024 * 1024, tx_bytes=1024 * 1024)
        stat = parse_stats("abc123", "web", raw)

        assert stat.network_rx_mb == 2.0
        assert stat.network_tx_mb == 1.0

    def test_block_io(self) -> None:
        raw = _make_raw_stats(blkio_read=50 * 1024 * 1024, blkio_write=25 * 1024 * 1024)
        stat = parse_stats("abc123", "web", raw)

        assert stat.block_read_mb == 50.0
        assert stat.block_write_mb == 25.0

    def test_pids(self) -> None:
        raw = _make_raw_stats(pids=42)
        stat = parse_stats("abc123", "web", raw)
        assert stat.pids == 42

    def test_zero_system_delta_returns_zero_cpu(self) -> None:
        raw = _make_raw_stats(system_cpu=1000, presystem_cpu=1000)
        stat = parse_stats("abc123", "web", raw)
        assert stat.cpu_percent == 0.0

    def test_container_id_and_name(self) -> None:
        raw = _make_raw_stats()
        stat = parse_stats("deadbeef", "my-app", raw)
        assert stat.container_id == "deadbeef"
        assert stat.name == "my-app"


class TestCollectAll:
    """Test StatsCollector.collect_all with a mock Docker client."""

    def _mock_container(self, cid: str, name: str, raw: dict) -> MagicMock:
        container = MagicMock()
        container.id = cid
        container.name = name
        container.stats.return_value = raw
        return container

    def test_collects_stats_for_all_running_containers(self) -> None:
        containers = [
            self._mock_container("c1", "web", _make_raw_stats(pids=5)),
            self._mock_container("c2", "db", _make_raw_stats(pids=10)),
            self._mock_container("c3", "cache", _make_raw_stats(pids=3)),
        ]

        client = MagicMock()
        client.containers.list.return_value = containers

        collector = StatsCollector(docker_client=client)
        results = collector.collect_all()

        assert len(results) == 3
        names = {s.name for s in results}
        assert names == {"web", "db", "cache"}

    def test_skips_containers_that_error(self) -> None:
        good = self._mock_container("c1", "web", _make_raw_stats())
        bad = MagicMock()
        bad.id = "c2"
        bad.name = "dying"
        bad.stats.side_effect = Exception("container stopped")

        client = MagicMock()
        client.containers.list.return_value = [good, bad]

        collector = StatsCollector(docker_client=client)
        results = collector.collect_all()

        assert len(results) == 1
        assert results[0].name == "web"
