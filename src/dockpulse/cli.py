"""DockPulse CLI -- Container Resource Profiler & Right-Sizer."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from dockpulse import __version__
from dockpulse.analyzer import Analyzer
from dockpulse.collector import StatsCollector
from dockpulse.compose_rewriter import ComposeRewriter
from dockpulse.config import Config, parse_duration
from dockpulse.dashboard import Dashboard
from dockpulse.reporter import Reporter
from dockpulse.rightsizer import RightSizer

console = Console()
app = typer.Typer(
    name="dockpulse",
    help="Container Resource Profiler & Right-Sizer for Docker.",
    rich_markup_mode="rich",
    no_args_is_help=True,
    add_completion=False,
)

_config = Config()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"dockpulse [bold cyan]{__version__}[/bold cyan]")
        raise typer.Exit()


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """DockPulse -- know exactly what your containers need."""


@app.command()
def profile(
    duration: str = typer.Option(
        "1h",
        "--duration",
        "-d",
        help="Profiling duration (e.g. 30m, 1h, 2h30m, 1d).",
    ),
    containers: str | None = typer.Option(
        None,
        "--containers",
        "-c",
        help="Comma-separated container IDs or names. Defaults to all running containers.",
    ),
    interval: float = typer.Option(
        1.0,
        "--interval",
        "-i",
        help="Seconds between stat samples.",
    ),
) -> None:
    """Profile running containers and record resource usage over time.

    Samples are stored in a local SQLite database for later analysis.
    Press Ctrl+C to stop early and keep collected data.
    """
    duration_secs = parse_duration(duration)
    cids = [c.strip() for c in containers.split(",")] if containers else None
    db = str(_config.resolved_db_path)

    console.print(
        f"[bold cyan]Profiling for {duration}[/bold cyan] "
        f"(interval={interval}s, db={db})"
    )

    collector = StatsCollector()
    count = 0

    def _on_sample(stat: object) -> None:
        nonlocal count
        count += 1
        if count % 10 == 0:
            console.print(f"  collected {count} samples ...", style="dim")

    try:
        collector.profile(
            container_ids=cids,
            duration_seconds=duration_secs,
            interval=interval,
            callback=_on_sample,
            db_path=db,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Profiling stopped early. Data saved.[/yellow]")

    console.print(f"[green]Done.[/green] {count} samples collected to {db}")


@app.command()
def analyze(
    fmt: str = typer.Option(
        "rich",
        "--format",
        "-f",
        help="Output format: rich, json, or html.",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path (required for json/html).",
    ),
) -> None:
    """Analyse the most recent profile and display results.

    Reads samples from the local database and computes percentile
    statistics, detects anomalies, and identifies bottlenecks.
    """
    import sqlite3
    from datetime import datetime, timezone

    from dockpulse.models import ContainerStats

    db = str(_config.resolved_db_path)
    if not Path(db).exists():
        console.print("[red]No profile data found.[/red] Run `dockpulse profile` first.")
        raise typer.Exit(1)

    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT * FROM samples ORDER BY name, timestamp"
    ).fetchall()
    conn.close()

    if not rows:
        console.print("[red]Profile database is empty.[/red]")
        raise typer.Exit(1)

    # Group rows by container name
    grouped: dict[str, list[ContainerStats]] = {}
    for row in rows:
        stat = ContainerStats(
            container_id=row[0],
            name=row[1],
            timestamp=datetime.fromisoformat(row[2]).replace(tzinfo=timezone.utc),
            cpu_percent=row[3],
            memory_usage_mb=row[4],
            memory_limit_mb=row[5],
            memory_percent=row[6],
            network_rx_mb=row[7],
            network_tx_mb=row[8],
            block_read_mb=row[9],
            block_write_mb=row[10],
            pids=row[11],
        )
        grouped.setdefault(stat.name, []).append(stat)

    analyzer = Analyzer()
    profiles = [analyzer.analyze(samples) for samples in grouped.values()]

    for p in profiles:
        anomalies = analyzer.detect_anomalies(p)
        for a in anomalies:
            console.print(f"[yellow]  ⚠ {a}[/yellow]")

    if len(profiles) > 1:
        console.print(f"\n[bold]{analyzer.find_bottleneck(profiles)}[/bold]")

    reporter = Reporter()
    if fmt == "json":
        if not output:
            console.print("[red]--output is required for JSON format.[/red]")
            raise typer.Exit(1)
        sizer = RightSizer(headroom_percent=_config.headroom_percent)
        report = sizer.generate_waste_report(profiles)
        reporter.to_json(report, output)
        console.print(f"[green]Report written to {output}[/green]")
    elif fmt == "html":
        if not output:
            console.print("[red]--output is required for HTML format.[/red]")
            raise typer.Exit(1)
        sizer = RightSizer(headroom_percent=_config.headroom_percent)
        report = sizer.generate_waste_report(profiles)
        reporter.to_html(report, output)
        console.print(f"[green]Report written to {output}[/green]")
    else:
        sizer = RightSizer(headroom_percent=_config.headroom_percent)
        report = sizer.generate_waste_report(profiles)
        reporter.to_terminal(report)


@app.command(name="right-size")
def right_size(
    compose_file: str = typer.Argument(
        ...,
        help="Path to the Docker Compose file to optimise.",
    ),
    headroom: float = typer.Option(
        20.0,
        "--headroom",
        "-H",
        help="Headroom percentage to add above p95 usage.",
    ),
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output path for the optimised compose file. Defaults to stdout diff.",
    ),
) -> None:
    """Right-size a Docker Compose file based on profiled resource usage.

    Reads the most recent profile data, computes recommendations, and
    rewrites the compose file with optimal resource limits.
    """
    import sqlite3
    from datetime import datetime, timezone

    from dockpulse.models import ContainerStats

    db = str(_config.resolved_db_path)
    if not Path(db).exists():
        console.print("[red]No profile data found.[/red] Run `dockpulse profile` first.")
        raise typer.Exit(1)

    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT * FROM samples ORDER BY name, timestamp").fetchall()
    conn.close()

    grouped: dict[str, list[ContainerStats]] = {}
    for row in rows:
        stat = ContainerStats(
            container_id=row[0],
            name=row[1],
            timestamp=datetime.fromisoformat(row[2]).replace(tzinfo=timezone.utc),
            cpu_percent=row[3],
            memory_usage_mb=row[4],
            memory_limit_mb=row[5],
            memory_percent=row[6],
            network_rx_mb=row[7],
            network_tx_mb=row[8],
            block_read_mb=row[9],
            block_write_mb=row[10],
            pids=row[11],
        )
        grouped.setdefault(stat.name, []).append(stat)

    analyzer = Analyzer()
    profiles = [analyzer.analyze(samples) for samples in grouped.values()]

    sizer = RightSizer(headroom_percent=headroom)
    recommendations = [sizer.recommend(p) for p in profiles]

    rewriter = ComposeRewriter()
    out = output or str(Path(compose_file).with_suffix(".optimized.yml"))
    rewriter.rewrite(compose_file, recommendations, out)

    diff_output = rewriter.diff(compose_file, out)
    if diff_output:
        console.print(diff_output)

    console.print(f"\n[green]Optimised compose file written to {out}[/green]")


@app.command()
def dashboard() -> None:
    """Launch a live terminal dashboard showing real-time container stats.

    The dashboard refreshes every second and shows CPU sparklines, memory
    bars, network I/O, and status indicators for all running containers.
    Press Ctrl+C to exit.
    """
    import time

    collector = StatsCollector()
    analyzer = Analyzer()
    dash = Dashboard(console=console)

    console.print("[bold cyan]Starting live dashboard...[/bold cyan] (Ctrl+C to exit)\n")

    history: dict[str, list] = {}

    try:
        with dash.render_live_context() as live:
            while True:
                stats = collector.collect_all()

                for s in stats:
                    history.setdefault(s.name, []).append(s)
                    # Keep last 300 samples per container (5 min at 1s interval)
                    if len(history[s.name]) > 300:
                        history[s.name] = history[s.name][-300:]

                profiles = []
                for _name, samples in history.items():
                    if len(samples) >= 2:
                        profiles.append(analyzer.analyze(samples))

                if profiles:
                    live.update(dash._build_table(profiles))

                time.sleep(1.0)
    except KeyboardInterrupt:
        console.print("\n[yellow]Dashboard stopped.[/yellow]")


@app.command()
def waste() -> None:
    """Show a waste report based on the most recent profiling data.

    Displays how much memory and CPU each container is wasting relative
    to its configured limits, along with right-sizing recommendations.
    """
    import sqlite3
    from datetime import datetime, timezone

    from dockpulse.models import ContainerStats

    db = str(_config.resolved_db_path)
    if not Path(db).exists():
        console.print("[red]No profile data found.[/red] Run `dockpulse profile` first.")
        raise typer.Exit(1)

    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT * FROM samples ORDER BY name, timestamp").fetchall()
    conn.close()

    if not rows:
        console.print("[red]Profile database is empty.[/red]")
        raise typer.Exit(1)

    grouped: dict[str, list[ContainerStats]] = {}
    for row in rows:
        stat = ContainerStats(
            container_id=row[0],
            name=row[1],
            timestamp=datetime.fromisoformat(row[2]).replace(tzinfo=timezone.utc),
            cpu_percent=row[3],
            memory_usage_mb=row[4],
            memory_limit_mb=row[5],
            memory_percent=row[6],
            network_rx_mb=row[7],
            network_tx_mb=row[8],
            block_read_mb=row[9],
            block_write_mb=row[10],
            pids=row[11],
        )
        grouped.setdefault(stat.name, []).append(stat)

    analyzer = Analyzer()
    profiles = [analyzer.analyze(samples) for samples in grouped.values()]

    sizer = RightSizer(headroom_percent=_config.headroom_percent)
    report = sizer.generate_waste_report(profiles)

    Dashboard(console=console).render_waste_report(report)
