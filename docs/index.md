# DockPulse Documentation

DockPulse is a container resource profiler and right-sizer for Docker. It
collects real-time resource usage data, computes percentile statistics,
identifies waste, and generates optimised `docker-compose.yml` resource limits.

## Getting Started

Install DockPulse and profile your first stack in under a minute:

```bash
pip install dockpulse
dockpulse profile --duration 10m
dockpulse waste
```

For full installation instructions, usage examples, and CLI reference, see the
[README](../README.md).

## Key Concepts

- **Profiling**: DockPulse collects CPU, memory, network, and disk I/O samples
  from running containers at configurable intervals and stores them in a local
  SQLite database.

- **Analysis**: Samples are aggregated into per-container profiles with p50,
  p95, and p99 percentiles. Anomaly detection flags memory pressure, CPU spikes,
  and over-provisioned containers.

- **Right-Sizing**: The right-sizing engine recommends resource limits based on
  observed p95 usage plus a configurable headroom percentage, ensuring
  containers have enough capacity without excessive waste.

- **Compose Rewriting**: Recommendations are applied directly to your
  `docker-compose.yml`, preserving existing comments and formatting via
  `ruamel.yaml`.

## Guides

- [Contributing](../CONTRIBUTING.md) -- development setup and workflow
- [Sample Compose File](../examples/sample-compose.yml) -- a multi-service
  stack to test DockPulse against
