"""DockPulse CLI -- Container Resource Profiler & Right-Sizer."""

from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

from dockpulse import __version__
from dockpulse.analyzer import Analyzer
from dockpulse.collector import StatsCollector
from dockpulse.compose_rewriter import ComposeRewriter
from dockpulse.config import Config, format_duration, parse_duration
from dockpulse.dashboard import Dashboard
from dockpulse.models import ContainerStats, ProfileResult
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


def _load_profiles_from_db(db_path: str) -> list[ProfileResult]:
    """Load the most recent profiling session and return analyzed profiles.

    Reads all samples from the SQLite database, groups them by container
    name, and runs the analyzer to produce ``ProfileResult`` objects.

    Raises:
        typer.Exit: If the database does not exist or contains no samples.
    """
    if not Path(db_path).exists():
        console.print("[red]No profile data found.[/red] Run `dockpulse profile` first.")
        raise typer.Exit(1)

    conn = sqlite3.connect(db_path)
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
    return [analyzer.analyze(samples) for samples in grouped.values()]


def _load_samples_for_session(db_path: str, session_id: str) -> list[ProfileResult]:
    """Load profiles for a specific session, matched by prefix.

    Raises:
        typer.Exit: If the database is missing or no matching session is found.
    """
    if not Path(db_path).exists():
        console.print("[red]No profile data found.[/red] Run `dockpulse profile` first.")
        raise typer.Exit(1)

    conn = sqlite3.connect(db_path)

    # Check if sessions table exists
    table_check = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
    ).fetchone()

    if not table_check:
        console.print("[red]No session data found.[/red] Re-run profiling to generate sessions.")
        conn.close()
        raise typer.Exit(1)

    row = conn.execute(
        "SELECT session_id, started_at, ended_at FROM sessions WHERE session_id LIKE ?",
        (f"{session_id}%",),
    ).fetchone()

    if not row:
        console.print(f"[red]No session matching '{session_id}'.[/red]")
        conn.close()
        raise typer.Exit(1)

    _full_session_id, started_at, ended_at = row

    query = "SELECT * FROM samples WHERE timestamp >= ? ORDER BY name, timestamp"
    params: list[str] = [started_at]
    if ended_at:
        query = "SELECT * FROM samples WHERE timestamp >= ? AND timestamp <= ? ORDER BY name, timestamp"
        params.append(ended_at)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        console.print(f"[red]No samples found for session '{session_id}'.[/red]")
        raise typer.Exit(1)

    grouped: dict[str, list[ContainerStats]] = {}
    for r in rows:
        stat = ContainerStats(
            container_id=r[0],
            name=r[1],
            timestamp=datetime.fromisoformat(r[2]).replace(tzinfo=timezone.utc),
            cpu_percent=r[3],
            memory_usage_mb=r[4],
            memory_limit_mb=r[5],
            memory_percent=r[6],
            network_rx_mb=r[7],
            network_tx_mb=r[8],
            block_read_mb=r[9],
            block_write_mb=r[10],
            pids=r[11],
        )
        grouped.setdefault(stat.name, []).append(stat)

    analyzer = Analyzer()
    return [analyzer.analyze(samples) for samples in grouped.values()]


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
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
        help="Suppress progress output during profiling.",
    ),
) -> None:
    """Profile running containers and record resource usage over time.

    Samples are stored in a local SQLite database for later analysis.
    Press Ctrl+C to stop early and keep collected data.
    """
    import uuid

    duration_secs = parse_duration(duration)
    cids = [c.strip() for c in containers.split(",")] if containers else None
    db = str(_config.resolved_db_path)

    if not quiet:
        console.print(
            f"[bold cyan]Profiling for {duration}[/bold cyan] "
            f"(interval={interval}s, db={db})"
        )

    session_id = uuid.uuid4().hex
    started_at = datetime.now(tz=timezone.utc).isoformat()

    # Ensure the sessions table exists
    _ensure_sessions_table(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO sessions (session_id, started_at, interval_seconds, status) VALUES (?, ?, ?, ?)",
        (session_id, started_at, interval, "running"),
    )
    conn.commit()
    conn.close()

    collector = StatsCollector()
    count = 0

    if quiet:
        def _on_sample(stat: object) -> None:
            nonlocal count
            count += 1

        with contextlib.suppress(KeyboardInterrupt):
            collector.profile(
                container_ids=cids,
                duration_seconds=duration_secs,
                interval=interval,
                callback=_on_sample,
                db_path=db,
            )
    else:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total} samples"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            estimated_samples = int(duration_secs / interval)
            task = progress.add_task("Profiling...", total=estimated_samples)

            def _on_sample_progress(stat: object) -> None:
                nonlocal count
                count += 1
                progress.advance(task)

            try:
                collector.profile(
                    container_ids=cids,
                    duration_seconds=duration_secs,
                    interval=interval,
                    callback=_on_sample_progress,
                    db_path=db,
                )
            except KeyboardInterrupt:
                console.print("\n[yellow]Profiling stopped early. Data saved.[/yellow]")

    ended_at = datetime.now(tz=timezone.utc).isoformat()
    conn = sqlite3.connect(db)
    sample_count_row = conn.execute(
        "SELECT COUNT(*) FROM samples WHERE timestamp >= ?", (started_at,)
    ).fetchone()
    sample_count = sample_count_row[0] if sample_count_row else count
    container_count_row = conn.execute(
        "SELECT COUNT(DISTINCT name) FROM samples WHERE timestamp >= ?", (started_at,)
    ).fetchone()
    container_count = container_count_row[0] if container_count_row else 0
    conn.execute(
        "UPDATE sessions SET ended_at=?, duration_seconds=?, container_count=?, sample_count=?, status=? WHERE session_id=?",
        (ended_at, duration_secs, container_count, sample_count, "completed", session_id),
    )
    conn.commit()
    conn.close()

    if not quiet:
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
    db = str(_config.resolved_db_path)
    profiles = _load_profiles_from_db(db)

    analyzer = Analyzer()
    for p in profiles:
        anomalies = analyzer.detect_anomalies(p)
        for a in anomalies:
            console.print(f"[yellow]  ⚠ {a}[/yellow]")

    if len(profiles) > 1:
        console.print(f"\n[bold]{analyzer.find_bottleneck(profiles)}[/bold]")

    reporter = Reporter()
    sizer = RightSizer(headroom_percent=_config.headroom_percent)
    report = sizer.generate_waste_report(profiles)

    if fmt == "json":
        if not output:
            console.print("[red]--output is required for JSON format.[/red]")
            raise typer.Exit(1)
        reporter.to_json(report, output)
        console.print(f"[green]Report written to {output}[/green]")
    elif fmt == "html":
        if not output:
            console.print("[red]--output is required for HTML format.[/red]")
            raise typer.Exit(1)
        reporter.to_html(report, output)
        console.print(f"[green]Report written to {output}[/green]")
    else:
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
    db = str(_config.resolved_db_path)
    profiles = _load_profiles_from_db(db)

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
def dashboard(
    refresh_rate: float = typer.Option(
        1.0,
        "--refresh-rate",
        "-r",
        help="Dashboard refresh interval in seconds.",
    ),
) -> None:
    """Launch a live terminal dashboard showing real-time container stats.

    The dashboard refreshes at the configured rate and shows CPU sparklines,
    memory bars, network I/O, and status indicators for all running containers.
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
                    if len(history[s.name]) > 300:
                        history[s.name] = history[s.name][-300:]

                profiles = []
                for _name, samples in history.items():
                    if len(samples) >= 2:
                        profiles.append(analyzer.analyze(samples))

                if profiles:
                    live.update(dash._build_table(profiles))

                time.sleep(refresh_rate)
    except KeyboardInterrupt:
        console.print("\n[yellow]Dashboard stopped.[/yellow]")


@app.command()
def waste() -> None:
    """Show a waste report based on the most recent profiling data.

    Displays how much memory and CPU each container is wasting relative
    to its configured limits, along with right-sizing recommendations.
    """
    db = str(_config.resolved_db_path)
    profiles = _load_profiles_from_db(db)

    sizer = RightSizer(headroom_percent=_config.headroom_percent)
    report = sizer.generate_waste_report(profiles)

    Dashboard(console=console).render_waste_report(report)


@app.command()
def sessions() -> None:
    """List all profiling sessions stored in the database.

    Shows session ID, date, duration, container count, sample count, and status.
    """
    db = str(_config.resolved_db_path)
    if not Path(db).exists():
        console.print("[red]No profile data found.[/red] Run `dockpulse profile` first.")
        raise typer.Exit(1)

    conn = sqlite3.connect(db)

    table_check = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
    ).fetchone()

    if not table_check:
        console.print("[yellow]No sessions table found.[/yellow] Re-run profiling to track sessions.")
        conn.close()
        raise typer.Exit(1)

    rows = conn.execute(
        "SELECT session_id, started_at, ended_at, duration_seconds, container_count, sample_count, status "
        "FROM sessions ORDER BY started_at DESC"
    ).fetchall()
    conn.close()

    if not rows:
        console.print("[yellow]No sessions recorded yet.[/yellow]")
        raise typer.Exit(0)

    table = Table(
        title="Profiling Sessions",
        title_style="bold cyan",
        expand=True,
        border_style="bright_blue",
    )
    table.add_column("Session ID", style="bold", no_wrap=True)
    table.add_column("Started", style="dim")
    table.add_column("Duration", justify="right")
    table.add_column("Containers", justify="right")
    table.add_column("Samples", justify="right")
    table.add_column("Status", justify="center")

    for row in rows:
        sid, started, _ended, dur_secs, containers_n, samples_n, status = row

        short_id = sid[:8] if sid else "?"
        started_str = started[:19].replace("T", " ") if started else "?"
        dur_str = format_duration(int(dur_secs)) if dur_secs else "?"
        containers_str = str(containers_n) if containers_n is not None else "?"
        samples_str = str(samples_n) if samples_n is not None else "?"

        status_style = {
            "completed": "green",
            "running": "yellow",
            "interrupted": "red",
        }.get(status, "dim")

        table.add_row(
            short_id,
            started_str,
            dur_str,
            containers_str,
            samples_str,
            Text(status or "?", style=status_style),
        )

    console.print(table)


@app.command()
def compare(
    session_a: str = typer.Argument(..., help="First session ID (or prefix)"),
    session_b: str = typer.Argument(..., help="Second session ID (or prefix)"),
) -> None:
    """Compare resource usage between two profiling sessions.

    Shows per-container deltas and trend indicators (increasing/decreasing/stable).
    """
    db = str(_config.resolved_db_path)

    profiles_a = _load_samples_for_session(db, session_a)
    profiles_b = _load_samples_for_session(db, session_b)

    lookup_a = {p.name: p for p in profiles_a}
    lookup_b = {p.name: p for p in profiles_b}
    all_names = sorted(set(lookup_a.keys()) | set(lookup_b.keys()))

    if not all_names:
        console.print("[yellow]No containers to compare.[/yellow]")
        raise typer.Exit(0)

    table = Table(
        title=f"Session Comparison: {session_a[:8]} vs {session_b[:8]}",
        title_style="bold cyan",
        expand=True,
        border_style="bright_blue",
    )
    table.add_column("Container", style="bold", no_wrap=True)
    table.add_column("CPU p95 (A)", justify="right")
    table.add_column("CPU p95 (B)", justify="right")
    table.add_column("CPU Delta", justify="right")
    table.add_column("CPU Trend", justify="center")
    table.add_column("Mem p95 (A)", justify="right")
    table.add_column("Mem p95 (B)", justify="right")
    table.add_column("Mem Delta", justify="right")
    table.add_column("Mem Trend", justify="center")

    threshold = 5.0

    for name in all_names:
        pa = lookup_a.get(name)
        pb = lookup_b.get(name)

        cpu_a = pa.cpu_p95 if pa else 0.0
        cpu_b = pb.cpu_p95 if pb else 0.0
        cpu_delta = cpu_b - cpu_a

        mem_a = pa.memory_p95_mb if pa else 0.0
        mem_b = pb.memory_p95_mb if pb else 0.0
        mem_delta = mem_b - mem_a

        def _trend_text(delta: float, threshold_pct: float, base: float) -> Text:
            pct = abs(delta) if base == 0 else abs(delta / base) * 100
            if pct < threshold_pct:
                return Text("→ stable", style="yellow")
            elif delta > 0:
                return Text("↑ increasing", style="red")
            else:
                return Text("↓ decreasing", style="green")

        cpu_trend = _trend_text(cpu_delta, threshold, cpu_a)
        mem_trend = _trend_text(mem_delta, threshold, mem_a)

        def _delta_str(delta: float, suffix: str = "") -> Text:
            sign = "+" if delta >= 0 else ""
            style = "red" if delta > 0 else ("green" if delta < 0 else "yellow")
            return Text(f"{sign}{delta:.1f}{suffix}", style=style)

        table.add_row(
            name,
            f"{cpu_a:.1f}%",
            f"{cpu_b:.1f}%",
            _delta_str(cpu_delta, "%"),
            cpu_trend,
            f"{mem_a:.1f} MB",
            f"{mem_b:.1f} MB",
            _delta_str(mem_delta, " MB"),
            mem_trend,
        )

    console.print(table)


@app.command()
def stack(
    compose_file: str = typer.Argument(None, help="Path to docker-compose.yml for dependency analysis"),
    fmt: str = typer.Option("rich", "--format", "-f", help="Output format: rich, json"),
) -> None:
    """Analyze a multi-container stack and identify bottlenecks.

    Provides service rankings, dependency analysis, and optimization recommendations.
    """
    from ruamel.yaml import YAML

    db = str(_config.resolved_db_path)
    profiles = _load_profiles_from_db(db)

    dependencies: list[dict[str, str]] = []
    if compose_file:
        compose_path = Path(compose_file)
        if not compose_path.exists():
            console.print(f"[red]Compose file not found: {compose_file}[/red]")
            raise typer.Exit(1)

        yaml = YAML()
        doc = yaml.load(compose_path)
        services = doc.get("services", {})

        for svc_name, svc_cfg in services.items():
            for dep in svc_cfg.get("depends_on", []):
                dep_name = dep if isinstance(dep, str) else str(dep)
                dependencies.append({
                    "source": svc_name,
                    "target": dep_name,
                    "type": "depends_on",
                })
            if isinstance(svc_cfg.get("networks"), list):
                for net in svc_cfg["networks"]:
                    dependencies.append({
                        "source": svc_name,
                        "target": net,
                        "type": "network",
                    })

    rankings: list[tuple[str, float]] = []
    for p in profiles:
        mem_pressure = (p.memory_p95_mb / p.memory_limit_mb) if p.memory_limit_mb > 0 else 0.0
        cpu_pressure = p.cpu_p95 / 100.0
        score = round(mem_pressure * 0.6 + cpu_pressure * 0.4, 3)
        rankings.append((p.name, score))
    rankings.sort(key=lambda x: x[1], reverse=True)

    analyzer = Analyzer()
    bottleneck = analyzer.find_bottleneck(profiles)

    total_cpu = sum(p.avg_cpu for p in profiles)
    total_mem = sum(p.memory_p95_mb for p in profiles)

    recommendations: list[str] = []
    for p in profiles:
        if p.memory_limit_mb > 0 and (p.memory_p95_mb / p.memory_limit_mb) > 0.80:
            recommendations.append(f"Increase memory limit for '{p.name}' (at {p.memory_p95_mb / p.memory_limit_mb:.0%} of limit)")
        if p.memory_limit_mb > 0 and (p.memory_p95_mb / p.memory_limit_mb) < 0.10 and p.cpu_p95 < 10.0:
            recommendations.append(f"Reduce resources for '{p.name}' (under 10% utilization)")
        if p.peak_cpu > 200.0:
            recommendations.append(f"Investigate CPU spikes in '{p.name}' (peak: {p.peak_cpu:.1f}%)")

    if not recommendations:
        recommendations.append("All services are within healthy resource bounds.")

    if fmt == "json":
        result = {
            "bottleneck": bottleneck,
            "total_cpu_percent": round(total_cpu, 2),
            "total_memory_mb": round(total_mem, 2),
            "service_rankings": [{"name": n, "score": s} for n, s in rankings],
            "dependencies": dependencies,
            "recommendations": recommendations,
        }
        console.print_json(json.dumps(result, indent=2))
        return

    console.print("\n[bold cyan]Stack Analysis[/bold cyan]")
    console.print(f"[bold]{bottleneck}[/bold]\n")

    rank_table = Table(
        title="Service Rankings (by resource pressure)",
        title_style="bold",
        expand=True,
        border_style="bright_blue",
    )
    rank_table.add_column("Rank", justify="center", style="dim", width=6)
    rank_table.add_column("Service", style="bold")
    rank_table.add_column("Pressure Score", justify="right")
    rank_table.add_column("CPU p95", justify="right")
    rank_table.add_column("Mem p95 (MB)", justify="right")

    profile_lookup = {p.name: p for p in profiles}
    for i, (name, score) in enumerate(rankings, 1):
        p = profile_lookup.get(name)
        score_style = "red" if score > 0.7 else ("yellow" if score > 0.4 else "green")
        rank_table.add_row(
            str(i),
            name,
            Text(f"{score:.3f}", style=score_style),
            f"{p.cpu_p95:.1f}%" if p else "?",
            f"{p.memory_p95_mb:.1f}" if p else "?",
        )

    console.print(rank_table)

    if dependencies:
        console.print()
        dep_table = Table(
            title="Service Dependencies",
            title_style="bold",
            border_style="bright_blue",
        )
        dep_table.add_column("Source", style="bold")
        dep_table.add_column("→", justify="center", style="dim")
        dep_table.add_column("Target", style="bold")
        dep_table.add_column("Type", style="dim")

        for dep in dependencies:
            dep_table.add_row(dep["source"], "→", dep["target"], dep["type"])
        console.print(dep_table)

    console.print(f"\n[bold]Total CPU usage:[/bold] {total_cpu:.1f}%")
    console.print(f"[bold]Total memory (p95):[/bold] {total_mem:.1f} MB\n")

    console.print("[bold]Recommendations:[/bold]")
    for rec in recommendations:
        console.print(f"  • {rec}")
    console.print()


@app.command()
def clean(
    all_sessions: bool = typer.Option(False, "--all", help="Delete all sessions and data"),
    session_id: str | None = typer.Option(None, "--session", "-s", help="Delete a specific session"),
) -> None:
    """Clean up profiling data from the local database."""
    db = str(_config.resolved_db_path)
    db_path = Path(db)

    if not db_path.exists():
        console.print("[yellow]No database found. Nothing to clean.[/yellow]")
        raise typer.Exit(0)

    if all_sessions:
        db_path.unlink()
        console.print("[green]All profiling data deleted.[/green]")
        return

    if session_id:
        conn = sqlite3.connect(db)

        table_check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        ).fetchone()
        if not table_check:
            console.print("[red]No sessions table found.[/red]")
            conn.close()
            raise typer.Exit(1)

        row = conn.execute(
            "SELECT session_id, started_at, ended_at FROM sessions WHERE session_id LIKE ?",
            (f"{session_id}%",),
        ).fetchone()

        if not row:
            console.print(f"[red]No session matching '{session_id}'.[/red]")
            conn.close()
            raise typer.Exit(1)

        full_id, started_at, ended_at = row

        if ended_at:
            conn.execute(
                "DELETE FROM samples WHERE timestamp >= ? AND timestamp <= ?",
                (started_at, ended_at),
            )
        else:
            conn.execute(
                "DELETE FROM samples WHERE timestamp >= ?",
                (started_at,),
            )

        conn.execute("DELETE FROM sessions WHERE session_id = ?", (full_id,))
        conn.commit()
        conn.close()

        console.print(f"[green]Session {full_id[:8]} and its samples deleted.[/green]")
        return

    console.print("[yellow]Specify --all to delete everything or --session/-s to delete a specific session.[/yellow]")


def _ensure_sessions_table(db_path: str) -> None:
    """Create the sessions table if it doesn't already exist."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
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
    conn.commit()
    conn.close()
