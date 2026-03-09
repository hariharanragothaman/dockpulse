"""Minimal Prometheus metrics exporter using only the standard library."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dockpulse.collector import StatsCollector


_MB_TO_BYTES = 1024 * 1024


def _escape_label(value: str) -> str:
    """Escape a Prometheus label value (backslash, newline, double-quote)."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_gauge(name: str, help_text: str, samples: list[tuple[str, float]]) -> str:
    """Format a single gauge metric family in Prometheus text exposition format.

    Args:
        name: Metric name (e.g. ``dockpulse_container_cpu_percent``).
        help_text: Human-readable description.
        samples: List of ``(label_set, value)`` pairs where *label_set*
            is the pre-formatted ``{key="val"}`` string.
    """
    lines = [f"# HELP {name} {help_text}", f"# TYPE {name} gauge"]
    for labels, value in samples:
        lines.append(f"{name}{labels} {value}")
    return "\n".join(lines)


class _MetricsHandler(BaseHTTPRequestHandler):
    """HTTP handler that serves ``/metrics`` in Prometheus text format."""

    exporter: PrometheusExporter

    def do_GET(self) -> None:
        if self.path == "/metrics":
            body = self.exporter._collect_metrics().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        pass


class PrometheusExporter:
    """Exports container stats as Prometheus-compatible metrics.

    Runs a lightweight HTTP server that serves metrics in Prometheus
    text exposition format at /metrics.
    """

    def __init__(self, port: int = 9090, collector: StatsCollector | None = None) -> None:
        from dockpulse.collector import StatsCollector as _StatsCollector

        self._port = port
        self._collector = collector or _StatsCollector()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the HTTP server in a background thread."""
        handler = type("Handler", (_MetricsHandler,), {"exporter": self})
        self._server = HTTPServer(("0.0.0.0", self._port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the HTTP server."""
        if self._server is not None:
            self._server.shutdown()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _collect_metrics(self) -> str:
        """Collect current container stats and format as Prometheus text.

        Metrics exported:
        - dockpulse_container_cpu_percent{container="name"} gauge
        - dockpulse_container_memory_usage_bytes{container="name"} gauge
        - dockpulse_container_memory_limit_bytes{container="name"} gauge
        - dockpulse_container_memory_percent{container="name"} gauge
        - dockpulse_container_network_rx_bytes{container="name"} gauge
        - dockpulse_container_network_tx_bytes{container="name"} gauge
        - dockpulse_container_block_read_bytes{container="name"} gauge
        - dockpulse_container_block_write_bytes{container="name"} gauge
        - dockpulse_container_pids{container="name"} gauge
        - dockpulse_containers_total gauge (total number of monitored containers)
        """
        stats = self._collector.collect_all()
        sections: list[str] = []

        cpu: list[tuple[str, float]] = []
        mem_usage: list[tuple[str, float]] = []
        mem_limit: list[tuple[str, float]] = []
        mem_pct: list[tuple[str, float]] = []
        net_rx: list[tuple[str, float]] = []
        net_tx: list[tuple[str, float]] = []
        blk_read: list[tuple[str, float]] = []
        blk_write: list[tuple[str, float]] = []
        pids: list[tuple[str, float]] = []

        for s in stats:
            labels = f'{{container="{_escape_label(s.name)}"}}'
            cpu.append((labels, s.cpu_percent))
            mem_usage.append((labels, s.memory_usage_mb * _MB_TO_BYTES))
            mem_limit.append((labels, s.memory_limit_mb * _MB_TO_BYTES))
            mem_pct.append((labels, s.memory_percent))
            net_rx.append((labels, s.network_rx_mb * _MB_TO_BYTES))
            net_tx.append((labels, s.network_tx_mb * _MB_TO_BYTES))
            blk_read.append((labels, s.block_read_mb * _MB_TO_BYTES))
            blk_write.append((labels, s.block_write_mb * _MB_TO_BYTES))
            pids.append((labels, float(s.pids)))

        sections.append(_format_gauge(
            "dockpulse_container_cpu_percent",
            "CPU usage percentage",
            cpu,
        ))
        sections.append(_format_gauge(
            "dockpulse_container_memory_usage_bytes",
            "Memory usage in bytes",
            mem_usage,
        ))
        sections.append(_format_gauge(
            "dockpulse_container_memory_limit_bytes",
            "Memory limit in bytes",
            mem_limit,
        ))
        sections.append(_format_gauge(
            "dockpulse_container_memory_percent",
            "Memory usage as a percentage of limit",
            mem_pct,
        ))
        sections.append(_format_gauge(
            "dockpulse_container_network_rx_bytes",
            "Total network bytes received",
            net_rx,
        ))
        sections.append(_format_gauge(
            "dockpulse_container_network_tx_bytes",
            "Total network bytes transmitted",
            net_tx,
        ))
        sections.append(_format_gauge(
            "dockpulse_container_block_read_bytes",
            "Total block device bytes read",
            blk_read,
        ))
        sections.append(_format_gauge(
            "dockpulse_container_block_write_bytes",
            "Total block device bytes written",
            blk_write,
        ))
        sections.append(_format_gauge(
            "dockpulse_container_pids",
            "Number of running processes",
            pids,
        ))
        sections.append(_format_gauge(
            "dockpulse_containers_total",
            "Total number of monitored containers",
            [("", float(len(stats)))],
        ))

        return "\n\n".join(sections) + "\n"
