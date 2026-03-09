FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src/ src/

RUN pip install --no-cache-dir build \
    && python -m build --wheel --outdir /build/dist

# ---------------------------------------------------------------------------

FROM python:3.12-slim

LABEL maintainer="Hariharan Ragothaman"
LABEL description="DockPulse - Container Resource Profiler & Right-Sizer"

RUN groupadd --gid 1000 dockpulse \
    && useradd --uid 1000 --gid dockpulse --create-home dockpulse

COPY --from=builder /build/dist/*.whl /tmp/

RUN pip install --no-cache-dir /tmp/*.whl \
    && rm -rf /tmp/*.whl

USER dockpulse
WORKDIR /home/dockpulse

ENTRYPOINT ["dockpulse"]
CMD ["--help"]
