<p align="center">
  <img src="assets/logo.png" alt="DockPulse Logo" width="400">
</p>

<h1 align="center">DockPulse</h1>

<p align="center">
  <strong>Your Docker containers are wasting resources. DockPulse tells you exactly how much.</strong>
</p>

<p align="center">
  <a href="https://github.com/hariharanragothaman/dockpulse/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/hariharanragothaman/dockpulse/ci.yml?branch=main&style=flat-square&logo=github&label=CI" alt="CI Status"></a>
  <a href="https://github.com/hariharanragothaman/dockpulse/blob/main/LICENSE"><img src="https://img.shields.io/github/license/hariharanragothaman/dockpulse?style=flat-square&color=blue" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue?style=flat-square&logo=python&logoColor=white" alt="Python Versions">
</p>

<p align="center">
  <a href="https://github.com/hariharanragothaman/dockpulse/stargazers"><img src="https://img.shields.io/github/stars/hariharanragothaman/dockpulse?style=flat-square&logo=github&color=yellow" alt="GitHub Stars"></a>
  <a href="https://github.com/hariharanragothaman/dockpulse/network/members"><img src="https://img.shields.io/github/forks/hariharanragothaman/dockpulse?style=flat-square&logo=github" alt="GitHub Forks"></a>
  <a href="https://github.com/hariharanragothaman/dockpulse/issues"><img src="https://img.shields.io/github/issues/hariharanragothaman/dockpulse?style=flat-square&logo=github" alt="Open Issues"></a>
  <a href="https://github.com/hariharanragothaman/dockpulse/pulls"><img src="https://img.shields.io/github/issues-pr/hariharanragothaman/dockpulse?style=flat-square&logo=github" alt="Pull Requests"></a>
</p>

<p align="center">
  <a href="https://hub.docker.com/r/hariharanragothaman/dockpulse"><img src="https://img.shields.io/docker/pulls/hariharanragothaman/dockpulse?style=flat-square" alt="Docker Pulls"></a>
  <a href="https://hub.docker.com/r/hariharanragothaman/dockpulse"><img src="https://img.shields.io/docker/image-size/hariharanragothaman/dockpulse?style=flat-square&label=image%20size" alt="Docker Image Size"></a>
</p>

<p align="center">
  <a href="https://pypi.org/project/dockpulse/"><img src="https://img.shields.io/pypi/v/dockpulse?style=flat-square&color=3775A9" alt="PyPI Version"></a>
  <a href="https://pypi.org/project/dockpulse/"><img src="https://img.shields.io/pypi/dm/dockpulse?style=flat-square&label=downloads" alt="PyPI Downloads"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/docker-%232496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/python-%233776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/sqlite-%23003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite">
  <img src="https://img.shields.io/badge/rich_cli-%23000000?style=flat-square&logo=gnometerminal&logoColor=white" alt="Rich CLI">
  <img src="https://img.shields.io/badge/code%20style-ruff-261230?style=flat-square&logo=ruff&logoColor=D7FF64" alt="Ruff">
  <img src="https://img.shields.io/badge/type%20checked-mypy-blue?style=flat-square" alt="mypy">
  <img src="https://img.shields.io/badge/PRs-welcome-brightgreen?style=flat-square" alt="PRs Welcome">
</p>

---

## The Problem

Most Docker containers run with either **no resource limits** (risking OOM kills and noisy neighbors) or **wildly over-provisioned limits** set by guesswork. Kubernetes has Vertical Pod Autoscaler for right-sizing, but **standalone Docker has nothing**.

DockPulse fills this gap. It profiles your containers over time, computes percentile-based resource usage, identifies waste, and **automatically rewrites your `docker-compose.yml` with data-driven resource limits**.

## Features

- **Container Profiling** -- Collect CPU, memory, network, and block I/O statistics from running containers over configurable time windows (minutes to days)
- **Percentile Analysis** -- Compute p50 / p95 / p99 resource usage with anomaly detection for memory pressure, CPU spikes, and chronic over-provisioning
- **Right-Sizing Engine** -- Generate recommended `deploy.resources.limits` and `reservations` based on observed p95 usage plus configurable headroom
- **Compose Rewriter** -- Automatically patch `docker-compose.yml` files with optimized limits while preserving comments and formatting (via `ruamel.yaml`)
- **Waste Reports** -- Quantify total memory and CPU waste across your entire stack with actionable savings numbers
- **Live Dashboard** -- Real-time Rich terminal UI with CPU sparklines, memory bars, and color-coded health indicators
- **SQLite Persistence** -- All profiling data is stored locally with zero external dependencies
- **Multiple Output Formats** -- Terminal (Rich), JSON, and styled HTML reports

## Quick Start

### Installation

```bash
pip install dockpulse
```

Or install from source:

```bash
git clone https://github.com/hariharanragothaman/dockpulse.git
cd dockpulse
pip install -e ".[dev]"
```

Or run via Docker:

```bash
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  hariharanragothaman/dockpulse profile --duration 1h
```

### Basic Usage

```bash
# Profile all running containers for 30 minutes
dockpulse profile --duration 30m

# Profile specific containers for 2 hours at 5-second intervals
dockpulse profile --duration 2h --containers web,db,redis --interval 5

# Analyze collected data
dockpulse analyze

# Right-size a compose file with 25% headroom
dockpulse right-size docker-compose.yml --headroom 25 -o docker-compose.optimized.yml

# View live dashboard
dockpulse dashboard

# Generate a waste report
dockpulse waste
```

## CLI Reference

### `dockpulse profile`

Profile running containers and record resource usage to a local SQLite database.

| Option | Default | Description |
|---|---|---|
| `--duration`, `-d` | `1h` | Profiling duration (e.g. `30m`, `1h`, `2h30m`, `1d`) |
| `--containers`, `-c` | all | Comma-separated container IDs or names |
| `--interval`, `-i` | `1.0` | Seconds between stat samples |

```
$ dockpulse profile --duration 30m
Profiling 3 containers for 30m (interval=1.0s)
  web      | collected 1800 samples
  db       | collected 1800 samples
  redis    | collected 1800 samples
Done. 5400 samples saved to ~/.dockpulse/profiles.db
```

### `dockpulse analyze`

Analyze the most recent profile and display results.

| Option | Default | Description |
|---|---|---|
| `--format`, `-f` | `rich` | Output format: `rich`, `json`, or `html` |
| `--output`, `-o` | -- | Output file path (required for `json`/`html`) |

```
$ dockpulse analyze
Container: web
  CPU   p50=12.3%  p95=34.1%  p99=52.8%   peak=67.2%
  MEM   p50=180MB  p95=245MB  p99=312MB   limit=1024MB
  Anomalies: Over-provisioned (p95 memory is 24% of limit)

Container: db
  CPU   p50=4.1%   p95=18.6%  p99=29.4%   peak=41.0%
  MEM   p50=420MB  p95=510MB  p99=580MB   limit=2048MB
  Anomalies: Over-provisioned (p95 memory is 25% of limit)

Container: redis
  CPU   p50=0.8%   p95=2.1%   p99=3.4%    peak=5.1%
  MEM   p50=28MB   p95=35MB   p99=42MB    limit=512MB
  Anomalies: Over-provisioned (p95 memory is 7% of limit)
```

### `dockpulse right-size`

Right-size a Docker Compose file based on profiled resource usage.

| Argument / Option | Default | Description |
|---|---|---|
| `COMPOSE_FILE` | required | Path to the Docker Compose file |
| `--headroom`, `-H` | `20` | Headroom percentage above p95 |
| `--output`, `-o` | auto | Output path for optimized file |

```
$ dockpulse right-size docker-compose.yml --headroom 25
--- docker-compose.yml
+++ docker-compose.optimized.yml
@@ services.web.deploy.resources @@
+    limits:
+      memory: 306M
+      cpus: '0.43'
+    reservations:
+      memory: 180M

@@ services.db.deploy.resources @@
-    limits:
-      memory: 2048M
+    limits:
+      memory: 638M
+      cpus: '0.24'
+    reservations:
+      memory: 420M

Savings: 1.44 GB memory, 1.83 CPU cores freed
Written to docker-compose.optimized.yml
```

### `dockpulse dashboard`

Launch a live terminal dashboard with real-time resource monitoring.

```
$ dockpulse dashboard
+----------------------------------------------------------------+
|  DockPulse - Container Resource Monitor          Ctrl+C to exit |
|                                                                 |
|  Container  CPU (sparkline)  Avg CPU  Memory         Status     |
|  web        ▂▃▅▃▂▁▂▃▆▄     12.3%    ██████░░ 45.2%  HEALTHY   |
|  db         ▁▁▂▁▁▁▁▂▃▂      4.1%    ████░░░░ 31.0%  HEALTHY   |
|  redis      ▁▁▁▁▁▁▁▁▁▁      0.8%    █░░░░░░░  8.2%  HEALTHY   |
|  worker     ▃▅▇▅▃▅▇█▇▅     78.4%    ███████░ 88.1%  WARNING   |
+----------------------------------------------------------------+
```

### `dockpulse waste`

Show a waste report for the most recent profiling session.

```
$ dockpulse waste
DockPulse Waste Report
======================
Container   Allocated  Used(p95)  Wasted     Utilization
web         1024 MB    245 MB     779 MB     24%
db          2048 MB    510 MB     1538 MB    25%
redis       512 MB     35 MB      477 MB     7%
-------------------------------------------------------
Total       3584 MB    790 MB     2794 MB    22%

You are wasting 2.73 GB of memory and 2.1 CPU cores across 3 containers.
Right-size with: dockpulse right-size docker-compose.yml
```

## Architecture

### Data Flow

```mermaid
flowchart LR
    Docker["Docker Daemon"]
    Collector["StatsCollector"]
    DB["SQLite DB"]
    Analyzer["Analyzer"]
    Profile["ProfileResult"]
    RightSizer["RightSizer"]
    Compose["ComposeRewriter"]
    Reporter["Reporter"]
    Dashboard["Dashboard"]
    Visualizer["Visualizer"]
    Prometheus["PrometheusExporter"]

    Docker -->|"/containers/stats API"| Collector
    Collector -->|"persist samples"| DB
    Collector -->|"live stream"| Dashboard
    Collector -->|"live stream"| Prometheus
    DB -->|"load samples"| Analyzer
    Analyzer -->|"percentiles + anomalies"| Profile
    Profile --> RightSizer
    Profile --> Reporter
    Profile --> Visualizer
    RightSizer -->|"recommendations"| Compose
    Compose -->|"optimized YAML"| ComposeFile["docker-compose.yml"]
    Reporter -->|"JSON / HTML / terminal"| Output["Reports"]
    Visualizer -->|"Plotly charts"| HTMLReport["Interactive HTML"]
    Dashboard -->|"Rich live UI"| Terminal["Terminal"]
    Prometheus -->|"/metrics"| PromScrape["Prometheus / Grafana"]
```

### Module Dependency Graph

```mermaid
flowchart TD
    CLI["cli.py"]
    Collector["collector.py"]
    AnalyzerMod["analyzer.py"]
    Models["models.py"]
    Config["config.py"]
    DashboardMod["dashboard.py"]
    ReporterMod["reporter.py"]
    RightSizerMod["rightsizer.py"]
    ComposeRewriterMod["compose_rewriter.py"]
    VisualizerMod["visualizer.py"]
    PrometheusMod["prometheus.py"]

    CLI --> Collector
    CLI --> AnalyzerMod
    CLI --> DashboardMod
    CLI --> ReporterMod
    CLI --> RightSizerMod
    CLI --> ComposeRewriterMod
    CLI --> VisualizerMod
    CLI --> PrometheusMod
    CLI --> Config
    CLI --> Models
    Collector --> Models
    AnalyzerMod --> Models
    DashboardMod --> Models
    ReporterMod --> Models
    RightSizerMod --> Models
    ComposeRewriterMod --> Models
    PrometheusMod --> Collector
```

### CLI Command Map

```mermaid
flowchart TD
    CLI["dockpulse"]
    Profile["profile"]
    Analyze["analyze"]
    RightSize["right-size"]
    Dash["dashboard"]
    Waste["waste"]
    Report["report"]
    Sessions["sessions"]
    Compare["compare"]
    Stack["stack"]
    Clean["clean"]
    Export["export"]

    CLI --> Profile
    CLI --> Analyze
    CLI --> RightSize
    CLI --> Dash
    CLI --> Waste
    CLI --> Report
    CLI --> Sessions
    CLI --> Compare
    CLI --> Stack
    CLI --> Clean
    CLI --> Export

    Profile ---|"collect stats over time"| SQLite["SQLite DB"]
    Analyze ---|"percentile analysis"| TermOut["Terminal / JSON / HTML"]
    RightSize ---|"optimize limits"| ComposeOut["Compose YAML"]
    Dash ---|"live monitoring"| LiveUI["Rich Live UI"]
    Waste ---|"quantify waste"| WasteOut["Waste Report"]
    Report ---|"interactive charts"| PlotlyOut["Plotly HTML"]
    Sessions ---|"list sessions"| SessionTable["Session Table"]
    Compare ---|"diff two sessions"| DeltaTable["Delta Table"]
    Stack ---|"multi-container analysis"| StackOut["Rankings + Bottleneck"]
    Clean ---|"delete data"| CleanDB["SQLite Cleanup"]
    Export ---|"Prometheus metrics"| MetricsOut["/metrics endpoint"]
```

DockPulse talks directly to the Docker daemon via the Docker SDK for Python. Stats are collected using the `/containers/{id}/stats` API endpoint and persisted to a local SQLite database for offline analysis.

The right-sizing engine applies a configurable headroom percentage on top of observed p95 usage. The compose rewriter uses `ruamel.yaml` to update files in-place without destroying comments or formatting.

## Comparison

| Feature | DockPulse | `docker stats` | Kubernetes VPA |
|---|:---:|:---:|:---:|
| Time-series profiling | Yes | No (snapshot only) | Yes |
| Percentile analysis | p50/p95/p99 | No | Yes |
| Anomaly detection | Yes | No | No |
| Compose file rewriting | Yes | No | N/A (k8s only) |
| Waste quantification | Yes | No | No |
| Live dashboard | Yes | Basic | No |
| Works without Kubernetes | Yes | Yes | No |
| Zero external dependencies | Yes | Yes | No (requires k8s) |

## Roadmap

- [x] Prometheus metrics export
- [x] Historical trend analysis and regression detection
- [x] GitHub Action for CI resource regression checks
- [x] Interactive Plotly HTML reports
- [x] Session management and comparison
- [x] Multi-container stack analysis
- [ ] Slack / Discord alert integration
- [ ] Cost estimation (map waste to cloud provider pricing)
- [ ] Grafana dashboard templates
- [ ] Container startup time profiling
- [ ] PyPI package publishing

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, workflow, and guidelines.

```bash
# Development setup
git clone https://github.com/hariharanragothaman/dockpulse.git
cd dockpulse
pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check src/ tests/

# Run type checker
mypy src/
```

## License

MIT License. See [LICENSE](LICENSE) for details.

---

<p align="center">
  Built with the <a href="https://docs.docker.com/engine/api/sdk/">Docker SDK for Python</a>,
  <a href="https://typer.tiangolo.com/">Typer</a>, and
  <a href="https://rich.readthedocs.io/">Rich</a>.
</p>

<p align="center">
  <a href="https://github.com/hariharanragothaman/dockpulse">
    <img src="https://img.shields.io/badge/Star_on_GitHub-⭐-yellow?style=for-the-badge&logo=github" alt="Star on GitHub">
  </a>
</p>
