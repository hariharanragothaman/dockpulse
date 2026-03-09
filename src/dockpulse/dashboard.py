"""Rich terminal dashboard for live container monitoring."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from dockpulse.models import ProfileResult, WasteReport

_SPARKLINE_CHARS = " ▁▂▃▄▅▆▇█"


def _sparkline(values: list[float], width: int = 12) -> str:
    """Render a list of values as a Unicode sparkline."""
    if not values:
        return " " * width

    # Take the last *width* values
    recent = values[-width:]
    lo, hi = min(recent), max(recent)
    span = hi - lo if hi != lo else 1.0

    return "".join(
        _SPARKLINE_CHARS[int((v - lo) / span * (len(_SPARKLINE_CHARS) - 1))]
        for v in recent
    )


def _usage_bar(percent: float, width: int = 20) -> Text:
    """Render a coloured usage bar."""
    filled = int(percent / 100 * width)
    filled = min(filled, width)

    if percent >= 80:
        colour = "red"
    elif percent >= 50:
        colour = "yellow"
    else:
        colour = "green"

    bar = Text()
    bar.append("█" * filled, style=colour)
    bar.append("░" * (width - filled), style="dim")
    bar.append(f" {percent:5.1f}%", style=colour)
    return bar


def _status_indicator(profile: ProfileResult) -> Text:
    """Return a coloured status dot based on resource pressure."""
    ratio = profile.memory_p95_mb / profile.memory_limit_mb if profile.memory_limit_mb > 0 else 0.0

    if ratio >= 0.80 or profile.peak_cpu > 200:
        return Text("● CRITICAL", style="bold red")
    if ratio >= 0.50 or profile.peak_cpu > 100:
        return Text("● WARNING", style="bold yellow")
    return Text("● HEALTHY", style="bold green")


class Dashboard:
    """Rich terminal dashboard for container resource visualisation."""

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()

    def _build_table(self, profiles: list[ProfileResult]) -> Table:
        table = Table(
            title="DockPulse - Container Resource Monitor",
            title_style="bold cyan",
            expand=True,
            border_style="bright_blue",
        )
        table.add_column("Container", style="bold", no_wrap=True)
        table.add_column("CPU (sparkline)", justify="center")
        table.add_column("Avg CPU %", justify="right")
        table.add_column("Memory", justify="center", width=30)
        table.add_column("Mem MB", justify="right")
        table.add_column("Net I/O (MB)", justify="right")
        table.add_column("Status", justify="center")

        for p in profiles:
            cpu_vals = [s.cpu_percent for s in p.samples]
            mem_pct = (
                (p.memory_p95_mb / p.memory_limit_mb * 100)
                if p.memory_limit_mb > 0
                else 0.0
            )
            last = p.samples[-1] if p.samples else None
            net_io = (
                f"↓{last.network_rx_mb:.1f} ↑{last.network_tx_mb:.1f}"
                if last
                else "-"
            )

            table.add_row(
                p.name,
                _sparkline(cpu_vals),
                f"{p.avg_cpu:.1f}%",
                _usage_bar(mem_pct),
                f"{p.memory_p95_mb:.1f}/{p.memory_limit_mb:.0f}",
                net_io,
                _status_indicator(p),
            )

        return table

    def render_live(self, profiles: list[ProfileResult]) -> None:
        """Display a live-updating dashboard panel.

        This method blocks and continuously refreshes the table.
        It is intended to be called from the CLI's ``dashboard`` command, which
        feeds updated profiles in a loop.
        """
        panel = Panel(
            self._build_table(profiles),
            border_style="bright_blue",
            padding=(1, 2),
        )
        self._console.print(panel)

    def render_live_context(self) -> Live:
        """Return a ``Rich.Live`` context manager for external refresh loops."""
        return Live(console=self._console, refresh_per_second=2)

    def render_waste_report(self, report: WasteReport) -> None:
        """Print a formatted waste report to the terminal."""
        table = Table(
            title="Resource Waste Report",
            title_style="bold red",
            expand=True,
            border_style="red",
        )
        table.add_column("Container", style="bold")
        table.add_column("Mem Limit (MB)", justify="right")
        table.add_column("Mem Rec. (MB)", justify="right", style="green")
        table.add_column("Mem Saved (MB)", justify="right", style="cyan")
        table.add_column("CPU Limit", justify="right")
        table.add_column("CPU Rec.", justify="right", style="green")
        table.add_column("Headroom", justify="right")

        for rec in report.recommendations:
            table.add_row(
                rec.container_name,
                f"{rec.current_memory_limit_mb:.0f}" if rec.current_memory_limit_mb > 0 else "none",
                f"{rec.recommended_memory_limit_mb:.0f}",
                f"{rec.memory_savings_mb:.0f}" if rec.memory_savings_mb > 0 else "-",
                f"{rec.current_cpu_limit:.2f}" if rec.current_cpu_limit > 0 else "none",
                f"{rec.recommended_cpu_limit:.2f}",
                f"{rec.headroom_percent:.0f}%",
            )

        summary = Table.grid(padding=(0, 2))
        summary.add_column(style="bold")
        summary.add_column()
        summary.add_row("Total memory allocated:", f"{report.total_memory_allocated_mb:.0f} MB")
        summary.add_row("Total memory used (p95):", f"{report.total_memory_used_p95_mb:.0f} MB")
        summary.add_row(
            "Total memory waste:",
            Text(f"{report.total_memory_waste_mb:.0f} MB ({report.waste_percentage:.1f}%)", style="bold red"),
        )

        self._console.print(table)
        self._console.print()
        self._console.print(Panel(summary, title="Summary", border_style="red"))
