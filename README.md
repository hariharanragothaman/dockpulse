# DockPulse

**Your Docker containers are wasting resources. DockPulse tells you exactly how much.**

[![PyPI version](https://img.shields.io/pypi/v/dockpulse.svg)](https://pypi.org/project/dockpulse/)
[![Python](https://img.shields.io/pypi/pyversions/dockpulse.svg)](https://pypi.org/project/dockpulse/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/hariharanragothaman/dockpulse/actions/workflows/ci.yml/badge.svg)](https://github.com/hariharanragothaman/dockpulse/actions/workflows/ci.yml)

---

DockPulse is a CLI tool that profiles Docker container resource usage over time,
identifies waste, and generates right-sized resource limits for your
`docker-compose.yml` files. Stop guessing at memory and CPU limits -- let
observed data drive your configuration.

## Features

- **Container Profiling** -- Collect CPU, memory, network, and block I/O
  statistics from running containers over configurable time windows.
- **Percentile Analysis** -- Compute p50/p95/p99 resource usage with anomaly
  detection for memory pressure, CPU spikes, and over-provisioning.
- **Right-Sizing Engine** -- Generate recommended `deploy.resources` limits
  based on observed p95 usage plus configurable headroom.
- **Compose Rewriter** -- Automatically patch `docker-compose.yml` files with
  optimised limits while preserving comments and formatting.
- **Waste Reports** -- Quantify total memory and CPU waste across your entire
  stack in terminal, JSON, or styled HTML output.
- **Live Dashboard** -- Real-time Rich terminal UI with CPU sparklines, memory
  bars, and health indicators for every container.

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

### Basic Usage

**Profile all running containers for 30 minutes:**

```bash
dockpulse profile --duration 30m
```

**Profile specific containers for 2 hours at 5-second intervals:**

```bash
dockpulse profile --duration 2h --containers web,db,redis --interval 5
```

**Analyse collected data:**

```bash
dockpulse analyze
```

**Right-size a compose file:**

```bash
dockpulse right-size docker-compose.yml --headroom 25 -o docker-compose.optimized.yml
```

**View live dashboard:**

```bash
dockpulse dashboard
```

**Generate a waste report:**

```bash
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
Profiling for 30m (interval=1.0s, db=~/.dockpulse/profiles.db)
  collected 10 samples ...
  collected 20 samples ...
Done. 1800 samples collected to ~/.dockpulse/profiles.db
```

### `dockpulse analyze`

Analyse the most recent profile and display results.

| Option | Default | Description |
|---|---|---|
| `--format`, `-f` | `rich` | Output format: `rich`, `json`, or `html` |
| `--output`, `-o` | -- | Output file path (required for `json`/`html`) |

### `dockpulse right-size`

Right-size a Docker Compose file based on profiled resource usage.

| Argument / Option | Default | Description |
|---|---|---|
| `COMPOSE_FILE` | required | Path to the Docker Compose file |
| `--headroom`, `-H` | `20` | Headroom percentage above p95 |
| `--output`, `-o` | auto | Output path for optimised file |

```
$ dockpulse right-size docker-compose.yml --headroom 25
--- docker-compose.yml
+++ docker-compose.optimized.yml
@@ services.web.deploy.resources @@
+    limits:
+      memory: 240M
+      cpus: '0.36'
+    reservations:
+      memory: 120M

Optimised compose file written to docker-compose.optimized.yml
```

### `dockpulse dashboard`

Launch a live terminal dashboard with real-time resource monitoring.

```
$ dockpulse dashboard
┌─────────────────────────────────────────────────────────────────┐
│  DockPulse - Container Resource Monitor                        │
│  Container  CPU (sparkline)  Avg CPU  Memory         Status    │
│  web        ▂▃▅▃▂▁▂▃▆▄     12.3%    ██████░░ 45.2%  HEALTHY  │
│  db         ▁▁▂▁▁▁▁▂▃▂      4.1%    ████░░░░ 31.0%  HEALTHY  │
│  redis      ▁▁▁▁▁▁▁▁▁▁      0.8%    █░░░░░░░  8.2%  HEALTHY  │
└─────────────────────────────────────────────────────────────────┘
```

### `dockpulse waste`

Show a waste report for the most recent profiling session.

### `dockpulse --version`

Print the installed version.

## Architecture

```
dockpulse/
  cli.py              Typer CLI entry point
  collector.py        Docker SDK stats streaming + SQLite persistence
  analyzer.py         Percentile computation and anomaly detection
  rightsizer.py        Right-sizing recommendations with headroom
  compose_rewriter.py  YAML-preserving compose file patching
  dashboard.py        Rich live terminal UI
  reporter.py         JSON / HTML / terminal report generation
  models.py           Dataclass-based data models
  config.py           Configuration and duration parsing
```

DockPulse talks directly to the Docker daemon via the Docker SDK for Python.
Stats are collected using the `/containers/{id}/stats` API endpoint and
persisted to a local SQLite database for offline analysis.

The right-sizing engine applies a configurable headroom percentage on top of
observed p95 usage. The compose rewriter uses `ruamel.yaml` to update files
in-place without destroying comments or formatting.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for
development setup, workflow, and guidelines.

## License

MIT License. See [LICENSE](LICENSE) for details.
