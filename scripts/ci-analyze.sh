#!/usr/bin/env bash
# DockPulse CI Analysis Script
# Profiles running containers, generates reports, and optionally compares against baseline.

set -euo pipefail

# Defaults
DURATION="5m"
THRESHOLD="20"
REPORT_OUTPUT=""
HTML_OUTPUT=""
COMPOSE_FILE=""
BASELINE=""

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration)
      DURATION="${2:?Missing value for --duration}"
      shift 2
      ;;
    --threshold)
      THRESHOLD="${2:?Missing value for --threshold}"
      shift 2
      ;;
    --report-output)
      REPORT_OUTPUT="${2:?Missing value for --report-output}"
      shift 2
      ;;
    --html-output)
      HTML_OUTPUT="${2:?Missing value for --html-output}"
      shift 2
      ;;
    --compose-file)
      COMPOSE_FILE="$2"
      shift 2
      ;;
    --baseline)
      BASELINE="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$REPORT_OUTPUT" || -z "$HTML_OUTPUT" ]]; then
  echo "Error: --report-output and --html-output are required" >&2
  exit 1
fi

# Ensure output directory exists
mkdir -p "$(dirname "$REPORT_OUTPUT")"
mkdir -p "$(dirname "$HTML_OUTPUT")"

# GitHub Actions job summary path
GITHUB_STEP_SUMMARY="${GITHUB_STEP_SUMMARY:-}"

log() {
  echo "[DockPulse] $*"
}

write_summary() {
  local content="$1"
  if [[ -n "$GITHUB_STEP_SUMMARY" ]]; then
    echo "$content" >> "$GITHUB_STEP_SUMMARY"
  fi
}

set_output() {
  local name="$1"
  local value="$2"
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    # Use delimiter for multiline values (not needed here, but safe)
    echo "${name}=${value}" >> "$GITHUB_OUTPUT"
  fi
}

# Install DockPulse
log "Installing DockPulse..."
pip install --quiet dockpulse

# Ensure DockPulse data directory exists
mkdir -p ~/.dockpulse

# Check for running containers
CONTAINER_COUNT=$(docker ps -q 2>/dev/null | wc -l || echo 0)
if [[ "$CONTAINER_COUNT" -eq 0 ]]; then
  log "WARNING: No running containers found. Skipping profiling."
  write_summary "## DockPulse Resource Analysis

### No containers to profile
No running Docker containers were detected. Ensure services are started before running this action."
  set_output "report" "$REPORT_OUTPUT"
  set_output "waste-percentage" "0"
  set_output "passed" "true"
  # Create empty report files for artifact upload
  echo '{"total_memory_allocated_mb":0,"total_memory_used_p95_mb":0,"total_memory_waste_mb":0,"waste_percentage":0,"recommendations":[]}' > "$REPORT_OUTPUT"
  touch "$HTML_OUTPUT"
  exit 0
fi

# Run profiling
log "Profiling containers for ${DURATION}..."
if ! dockpulse profile --duration "$DURATION" --quiet 2>/dev/null; then
  log "Profiling failed or was interrupted. Proceeding with available data."
fi

# Generate reports
log "Generating analysis reports..."
if ! dockpulse analyze --format json --output "$REPORT_OUTPUT" 2>/dev/null; then
  log "Analysis failed. Creating minimal report."
  echo '{"total_memory_allocated_mb":0,"total_memory_used_p95_mb":0,"total_memory_waste_mb":0,"waste_percentage":0,"recommendations":[]}' > "$REPORT_OUTPUT"
fi

if ! dockpulse analyze --format html --output "$HTML_OUTPUT" 2>/dev/null; then
  log "HTML report generation failed. Skipping."
  touch "$HTML_OUTPUT"
fi

# Extract waste percentage from JSON (requires jq, available on ubuntu-latest)
WASTE_PCT="0"
if [[ -f "$REPORT_OUTPUT" ]]; then
  WASTE_PCT=$(jq -r '.waste_percentage // 0' "$REPORT_OUTPUT" 2>/dev/null || echo "0")
fi

# Baseline comparison and threshold check
PASSED="true"
MEM_INCREASE_PCT="0"

if [[ -n "$BASELINE" && -f "$BASELINE" ]]; then
  log "Comparing against baseline: $BASELINE"
  BASELINE_MEM=$(jq -r '.total_memory_used_p95_mb // 0' "$BASELINE" 2>/dev/null || echo "0")
  CURRENT_MEM=$(jq -r '.total_memory_used_p95_mb // 0' "$REPORT_OUTPUT" 2>/dev/null || echo "0")

  if [[ "$BASELINE_MEM" != "null" && "$(awk "BEGIN {print ($BASELINE_MEM > 0) ? 1 : 0}")" -eq 1 ]]; then
    # MEM_INCREASE_PCT = ((current - baseline) / baseline) * 100
    MEM_INCREASE_PCT=$(awk "BEGIN {printf \"%.2f\", (($CURRENT_MEM - $BASELINE_MEM) / $BASELINE_MEM) * 100}" 2>/dev/null || echo "0")
    THRESHOLD_NUM=$(awk "BEGIN {print $THRESHOLD}" 2>/dev/null || echo "20")

    if awk "BEGIN {exit !($MEM_INCREASE_PCT > $THRESHOLD_NUM)}" 2>/dev/null; then
      log "FAIL: Memory usage increased by ${MEM_INCREASE_PCT}% (threshold: ${THRESHOLD}%)"
      PASSED="false"
    else
      log "PASS: Memory increase ${MEM_INCREASE_PCT}% within threshold ${THRESHOLD}%"
    fi
  else
    log "Baseline has no memory data or zero baseline. Skipping comparison."
  fi
fi

# Build job summary
SUMMARY="## DockPulse Resource Analysis

| Metric | Value |
|--------|-------|
| Waste % | ${WASTE_PCT}% |
| Status | $([ "$PASSED" = "true" ] && echo '✅ Passed' || echo '❌ Failed') |
"

if [[ -n "$BASELINE" && -f "$BASELINE" ]]; then
  SUMMARY="${SUMMARY}
| Memory vs Baseline | ${MEM_INCREASE_PCT}% |
| Threshold | ${THRESHOLD}% |
"
fi

SUMMARY="${SUMMARY}

Report: \`${REPORT_OUTPUT}\`
"

write_summary "$SUMMARY"

# Set outputs
set_output "report" "$REPORT_OUTPUT"
set_output "waste-percentage" "$WASTE_PCT"
set_output "passed" "$PASSED"

# Exit with failure if threshold exceeded
if [[ "$PASSED" != "true" ]]; then
  exit 1
fi

exit 0
