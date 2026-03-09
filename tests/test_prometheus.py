"""Tests for the Prometheus metrics exporter."""

from __future__ import annotations

import threading
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from dockpulse.models import ContainerStats
from dockpulse.prometheus import PrometheusExporter, _escape_label, _format_gauge


def _make_stats(
    *,
    name: str = "web",
    cpu: float = 25.5,
    mem_usage_mb: float = 128.0,
    mem_limit_mb: float = 512.0,
    mem_pct: float = 25.0,
    net_rx_mb: float = 10.0,
    net_tx_mb: float = 5.0,
    blk_read_mb: float = 100.0,
    blk_write_mb: float = 50.0,
    pids: int = 12,
) -> ContainerStats:
    from datetime import datetime, timezone

    return ContainerStats(
        container_id="abc123",
        name=name,
        timestamp=datetime.now(tz=timezone.utc),
        cpu_percent=cpu,
        memory_usage_mb=mem_usage_mb,
        memory_limit_mb=mem_limit_mb,
        memory_percent=mem_pct,
        network_rx_mb=net_rx_mb,
        network_tx_mb=net_tx_mb,
        block_read_mb=blk_read_mb,
        block_write_mb=blk_write_mb,
        pids=pids,
    )


class TestEscapeLabel:
    def test_plain_string(self) -> None:
        assert _escape_label("web") == "web"

    def test_double_quote(self) -> None:
        assert _escape_label('my"app') == 'my\\"app'

    def test_backslash(self) -> None:
        assert _escape_label("path\\to") == "path\\\\to"

    def test_newline(self) -> None:
        assert _escape_label("line\nbreak") == "line\\nbreak"

    def test_combined(self) -> None:
        assert _escape_label('a\\b"c\nd') == 'a\\\\b\\"c\\nd'


class TestFormatGauge:
    def test_basic_gauge(self) -> None:
        output = _format_gauge("test_metric", "A test", [('', 42.0)])
        assert "# HELP test_metric A test" in output
        assert "# TYPE test_metric gauge" in output
        assert "test_metric 42.0" in output

    def test_gauge_with_labels(self) -> None:
        output = _format_gauge(
            "cpu_percent",
            "CPU usage",
            [
                ('{container="web"}', 25.0),
                ('{container="api"}', 50.0),
            ],
        )
        assert 'cpu_percent{container="web"} 25.0' in output
        assert 'cpu_percent{container="api"} 50.0' in output

    def test_empty_samples(self) -> None:
        output = _format_gauge("empty_metric", "Empty", [])
        assert "# HELP empty_metric Empty" in output
        assert "# TYPE empty_metric gauge" in output
        lines = output.strip().split("\n")
        assert len(lines) == 2


class TestCollectMetrics:
    def test_single_container(self) -> None:
        mock_collector = MagicMock()
        mock_collector.collect_all.return_value = [_make_stats(name="web", cpu=30.0)]

        exporter = PrometheusExporter(port=0, collector=mock_collector)
        output = exporter._collect_metrics()

        assert "dockpulse_container_cpu_percent" in output
        assert "dockpulse_container_memory_usage_bytes" in output
        assert "dockpulse_container_memory_limit_bytes" in output
        assert "dockpulse_container_memory_percent" in output
        assert "dockpulse_container_network_rx_bytes" in output
        assert "dockpulse_container_network_tx_bytes" in output
        assert "dockpulse_container_block_read_bytes" in output
        assert "dockpulse_container_block_write_bytes" in output
        assert "dockpulse_container_pids" in output
        assert "dockpulse_containers_total" in output

    def test_memory_conversion_to_bytes(self) -> None:
        mock_collector = MagicMock()
        mock_collector.collect_all.return_value = [
            _make_stats(name="web", mem_usage_mb=128.0, mem_limit_mb=512.0)
        ]

        exporter = PrometheusExporter(port=0, collector=mock_collector)
        output = exporter._collect_metrics()

        expected_usage = 128.0 * 1024 * 1024
        expected_limit = 512.0 * 1024 * 1024
        assert str(expected_usage) in output
        assert str(expected_limit) in output

    def test_multiple_containers(self) -> None:
        mock_collector = MagicMock()
        mock_collector.collect_all.return_value = [
            _make_stats(name="web", cpu=30.0),
            _make_stats(name="api", cpu=60.0),
            _make_stats(name="db", cpu=10.0),
        ]

        exporter = PrometheusExporter(port=0, collector=mock_collector)
        output = exporter._collect_metrics()

        assert 'container="web"' in output
        assert 'container="api"' in output
        assert 'container="db"' in output
        assert "dockpulse_containers_total 3.0" in output

    def test_no_containers(self) -> None:
        mock_collector = MagicMock()
        mock_collector.collect_all.return_value = []

        exporter = PrometheusExporter(port=0, collector=mock_collector)
        output = exporter._collect_metrics()

        assert "dockpulse_containers_total 0.0" in output

    def test_special_characters_in_name(self) -> None:
        mock_collector = MagicMock()
        mock_collector.collect_all.return_value = [
            _make_stats(name='my"container')
        ]

        exporter = PrometheusExporter(port=0, collector=mock_collector)
        output = exporter._collect_metrics()

        assert 'container="my\\"container"' in output

    def test_network_bytes_conversion(self) -> None:
        mock_collector = MagicMock()
        mock_collector.collect_all.return_value = [
            _make_stats(name="web", net_rx_mb=10.0, net_tx_mb=5.0)
        ]

        exporter = PrometheusExporter(port=0, collector=mock_collector)
        output = exporter._collect_metrics()

        expected_rx = 10.0 * 1024 * 1024
        expected_tx = 5.0 * 1024 * 1024
        assert str(expected_rx) in output
        assert str(expected_tx) in output

    def test_pids_as_float(self) -> None:
        mock_collector = MagicMock()
        mock_collector.collect_all.return_value = [_make_stats(name="web", pids=42)]

        exporter = PrometheusExporter(port=0, collector=mock_collector)
        output = exporter._collect_metrics()

        assert "dockpulse_container_pids" in output
        assert "42.0" in output


class TestExporterLifecycle:
    def test_start_and_stop(self) -> None:
        mock_collector = MagicMock()
        mock_collector.collect_all.return_value = []

        exporter = PrometheusExporter(port=0, collector=mock_collector)
        exporter.start()

        assert exporter._server is not None
        assert exporter._thread is not None
        assert exporter._thread.is_alive()

        exporter.stop()

        assert exporter._server is None
        assert exporter._thread is None

    def test_stop_without_start(self) -> None:
        mock_collector = MagicMock()
        exporter = PrometheusExporter(port=0, collector=mock_collector)
        exporter.stop()

    def test_http_serves_metrics(self) -> None:
        mock_collector = MagicMock()
        mock_collector.collect_all.return_value = [_make_stats(name="web")]

        exporter = PrometheusExporter(port=0, collector=mock_collector)
        exporter.start()

        try:
            port = exporter._server.server_address[1]
            url = f"http://localhost:{port}/metrics"
            with urllib.request.urlopen(url, timeout=5) as resp:
                body = resp.read().decode()
                assert resp.status == 200
                assert "dockpulse_container_cpu_percent" in body
                content_type = resp.headers.get("Content-Type", "")
                assert "text/plain" in content_type
        finally:
            exporter.stop()

    def test_http_404_on_other_paths(self) -> None:
        mock_collector = MagicMock()
        mock_collector.collect_all.return_value = []

        exporter = PrometheusExporter(port=0, collector=mock_collector)
        exporter.start()

        try:
            port = exporter._server.server_address[1]
            url = f"http://localhost:{port}/health"
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(url, timeout=5)
            assert exc_info.value.code == 404
        finally:
            exporter.stop()

    def test_default_collector_created(self) -> None:
        with patch("dockpulse.collector.docker") as mock_docker:
            mock_docker.from_env.return_value = MagicMock()
            exporter = PrometheusExporter(port=0)
            from dockpulse.collector import StatsCollector

            assert isinstance(exporter._collector, StatsCollector)
