#!/usr/bin/env bash
#
# DockPulse Live Demo
#
# Spins up the top 10 most popular Docker Hub images, profiles them with
# DockPulse, starts Prometheus + Grafana, and generates reports.
#
# Usage:
#   ./run-demo.sh                  # Full demo (3-minute profile)
#   ./run-demo.sh --duration 5m    # Custom profiling duration
#   ./run-demo.sh --skip-grafana   # Skip Prometheus/Grafana stack
#   ./run-demo.sh --cleanup        # Tear everything down
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DURATION="${DURATION:-3m}"
SKIP_GRAFANA=false
CLEANUP_ONLY=false

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}[DockPulse Demo]${NC} $*"; }
ok()    { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; }

usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --duration DURATION   Profiling duration (default: 3m)"
    echo "  --skip-grafana        Skip Prometheus + Grafana stack"
    echo "  --cleanup             Tear down all demo containers and exit"
    echo "  -h, --help            Show this help message"
    exit 0
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --duration)    DURATION="$2"; shift 2 ;;
        --skip-grafana) SKIP_GRAFANA=true; shift ;;
        --cleanup)     CLEANUP_ONLY=true; shift ;;
        -h|--help)     usage ;;
        *)             error "Unknown option: $1"; usage ;;
    esac
done

cleanup() {
    info "Tearing down demo containers..."
    docker compose -f "$SCRIPT_DIR/docker-compose.yml" down -v --remove-orphans 2>/dev/null || true
    if [[ "$SKIP_GRAFANA" == false ]]; then
        docker compose -f "$REPO_ROOT/examples/prometheus/docker-compose.yml" down -v --remove-orphans 2>/dev/null || true
    fi
    ok "Cleanup complete."
}

if [[ "$CLEANUP_ONLY" == true ]]; then
    cleanup
    exit 0
fi

# ── Preflight checks ───────────────────────────────────────────────
info "Running preflight checks..."

if ! command -v docker &>/dev/null; then
    error "Docker is not installed. Please install Docker first."
    exit 1
fi

if ! docker info &>/dev/null 2>&1; then
    error "Docker daemon is not running. Please start Docker first."
    exit 1
fi

# Activate the project venv if it exists and dockpulse isn't already available
if ! command -v dockpulse &>/dev/null; then
    if [[ -f "$REPO_ROOT/.venv/bin/activate" ]]; then
        info "Activating project virtualenv..."
        # shellcheck disable=SC1091
        source "$REPO_ROOT/.venv/bin/activate"
    fi
fi

if ! command -v dockpulse &>/dev/null; then
    warn "dockpulse not found in PATH. Trying pip install..."
    pip install -e "$REPO_ROOT" || {
        error "Failed to install dockpulse."
        error "Activate your virtualenv first, or run: pip install -e $REPO_ROOT"
        exit 1
    }
fi

ok "All preflight checks passed."

# ── Step 1: Start the top 10 containers ────────────────────────────
echo ""
echo -e "${BOLD}━━━ Step 1/5: Starting Top 10 Docker Hub Containers ━━━${NC}"
info "Pulling and starting containers..."

docker compose -f "$SCRIPT_DIR/docker-compose.yml" up -d --pull always

info "Waiting for containers to stabilize (30 seconds)..."
sleep 30

RUNNING=$(docker compose -f "$SCRIPT_DIR/docker-compose.yml" ps --status running -q | wc -l | tr -d ' ')
ok "$RUNNING containers running."

# ── Step 2: Start Prometheus + Grafana ─────────────────────────────
if [[ "$SKIP_GRAFANA" == false ]]; then
    echo ""
    echo -e "${BOLD}━━━ Step 2/5: Starting Prometheus + Grafana ━━━${NC}"
    docker compose -f "$REPO_ROOT/examples/prometheus/docker-compose.yml" up -d
    ok "Prometheus running at http://localhost:9091"
    ok "Grafana running at http://localhost:3000 (admin/admin)"
fi

# ── Step 3: Start DockPulse Prometheus exporter ────────────────────
echo ""
echo -e "${BOLD}━━━ Step 3/5: Starting DockPulse Prometheus Exporter ━━━${NC}"

# Kill any existing exporter
pkill -f "dockpulse export" 2>/dev/null || true
sleep 1

dockpulse export --port 9090 &
EXPORTER_PID=$!
sleep 2

if kill -0 $EXPORTER_PID 2>/dev/null; then
    ok "Prometheus exporter running at http://localhost:9090/metrics (PID: $EXPORTER_PID)"
else
    error "Failed to start Prometheus exporter."
    exit 1
fi

# ── Step 4: Profile containers ─────────────────────────────────────
echo ""
echo -e "${BOLD}━━━ Step 4/5: Profiling Containers (${DURATION}) ━━━${NC}"
info "This will take ${DURATION}. Data streams to Grafana in real time."
if [[ "$SKIP_GRAFANA" == false ]]; then
    info "Open Grafana now: ${BOLD}http://localhost:3000${NC}"
    echo ""
    info "  Dashboards:"
    info "    • Container Resource Overview  → /d/dockpulse-overview"
    info "    • Alerts & Thresholds          → /d/dockpulse-alerts"
    info "    • Right-Sizing & Waste         → /d/dockpulse-rightsizing"
    echo ""
fi

dockpulse profile --duration "$DURATION"
ok "Profiling complete."

# ── Step 5: Generate reports ───────────────────────────────────────
echo ""
echo -e "${BOLD}━━━ Step 5/5: Generating Reports ━━━${NC}"

info "Analysis results:"
echo ""
dockpulse analyze
echo ""

info "Waste report:"
echo ""
dockpulse waste
echo ""

info "Generating interactive HTML report..."
REPORT_PATH="$SCRIPT_DIR/demo-report.html"
dockpulse report --output "$REPORT_PATH" --type profile
ok "HTML report saved to $REPORT_PATH"

info "Cost estimation (AWS Fargate):"
echo ""
dockpulse cost --provider aws
echo ""

# ── Summary ────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}${BOLD}  Demo Complete!${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${BOLD}Containers profiled:${NC}  $RUNNING"
echo -e "  ${BOLD}HTML report:${NC}          $REPORT_PATH"
if [[ "$SKIP_GRAFANA" == false ]]; then
    echo -e "  ${BOLD}Grafana dashboards:${NC}   http://localhost:3000 (admin/admin)"
    echo -e "  ${BOLD}Prometheus:${NC}           http://localhost:9091"
fi
echo -e "  ${BOLD}Metrics endpoint:${NC}     http://localhost:9090/metrics"
echo ""
echo -e "  ${BOLD}Explore further:${NC}"
echo -e "    dockpulse sessions           # list profiling sessions"
echo -e "    dockpulse right-size examples/demo/docker-compose.yml"
echo -e "    dockpulse stack examples/demo/docker-compose.yml"
echo ""
echo -e "  ${BOLD}Cleanup:${NC}"
echo -e "    ./run-demo.sh --cleanup      # tear down all containers"
echo ""
echo -e "  ${YELLOW}Note: Prometheus exporter is still running (PID: $EXPORTER_PID).${NC}"
echo -e "  ${YELLOW}Grafana dashboards continue to update in real time.${NC}"
echo -e "  ${YELLOW}Kill the exporter with: kill $EXPORTER_PID${NC}"
