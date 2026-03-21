# DockPulse Live Demo

Profile the **top 10 most popular Docker Hub images** and visualize the results in Grafana.

## What's Included

| Container | Image | Purpose | Deliberate Misconfiguration |
|-----------|-------|---------|----------------------------|
| nginx | `nginx:alpine` | Web server | 512M limit for ~5M actual usage |
| redis | `redis:7-alpine` | In-memory cache | Moderate over-provisioning |
| postgres | `postgres:16-alpine` | Relational DB | 2048M limit, mostly idle |
| python-api | `python:3.12-slim` | API with CPU work | CPU-intensive hash computation |
| node-worker | `node:20-alpine` | Background worker | Periodic JSON serialization |
| memcached | `memcached:alpine` | Distributed cache | 512M limit for 32M config |
| mysql | `mysql:8.0` | Relational DB | 2048M limit, mostly idle |
| mongo | `mongo:7` | Document DB | 1024M limit, mostly idle |
| httpd | `httpd:alpine` | Web server | 512M limit for comparison |
| rabbitmq | `rabbitmq:3-management` | Message broker | Management UI enabled |

A **traffic generator** sends HTTP requests to nginx, httpd, and the Python API to produce realistic network I/O.

## Quick Start

```bash
cd examples/demo
./run-demo.sh
```

This will:
1. Pull and start all 10 containers + traffic generator
2. Start Prometheus + Grafana (auto-provisioned dashboards)
3. Start the DockPulse Prometheus exporter
4. Profile all containers for 3 minutes
5. Generate analysis, waste report, HTML report, and cost estimate

## Options

```bash
./run-demo.sh --duration 5m      # Longer profiling window
./run-demo.sh --skip-grafana     # Skip the Grafana stack
./run-demo.sh --cleanup          # Tear down everything
```

## Grafana Dashboards

After running the demo, open **http://localhost:3000** (admin/admin):

- **Container Resource Overview** — CPU, memory, network, disk I/O across all containers
- **Alerts & Thresholds** — active alerts, threshold monitoring, 5m rolling aggregates
- **Right-Sizing & Waste Analysis** — fleet utilization, waste metrics, usage vs limits

The dashboards update in real time as long as the exporter is running.

## Cleanup

```bash
./run-demo.sh --cleanup
```
