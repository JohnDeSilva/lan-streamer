FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/root \
    UV_CACHE_DIR=/tmp/.cache/uv \
    SCAN_AGENT_CONFIG=/data/config.json \
    PYTHONPATH=/app/src:/app/agent/src

# Install system dependencies: ffmpeg provides ffprobe for Pass 3 technical scanning
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Copy dependency files and install agent dependencies
COPY agent/pyproject.toml agent/uv.lock* /app/agent/
RUN uv --directory /app/agent sync --frozen --no-install-project 2>/dev/null || uv --directory /app/agent sync --no-install-project

# Copy source trees
COPY src/ /app/src/
COPY agent/src/ /app/agent/src/

# Install the agent project itself
RUN uv --directory /app/agent pip install --no-deps -e .

EXPOSE 8800

# Mount points for media and persistent data
VOLUME ["/media", "/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["curl", "-f", "http://localhost:8800/api/v1/health"]

ENTRYPOINT ["/app/agent/.venv/bin/python", "-m", "scan_agent.serve"]
