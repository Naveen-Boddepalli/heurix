# ==============================================================================
# Dockerfile for Heurix (hx) - Deterministic Codebase Scanner & YAML Synthesizer
# ==============================================================================
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build tools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy project files
COPY pyproject.toml README.md ./
COPY src ./src

# Build wheel package
RUN pip wheel --no-deps --no-build-isolation --no-cache-dir -w /app/dist .

# ==============================================================================
# Production Runtime Stage
# ==============================================================================
FROM python:3.12-slim AS runner

LABEL org.opencontainers.image.title="Heurix" \
      org.opencontainers.image.description="Deterministic Codebase Scanner & Automated YAML Synthesizer" \
      org.opencontainers.image.url="https://github.com/Naveen-Boddepalli/heurix" \
      org.opencontainers.image.source="https://github.com/Naveen-Boddepalli/heurix" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/home/heurix/.local/bin:${PATH}"

# Install git for repo detection & create non-root user
RUN apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/* /var/log/* /tmp/* && \
    useradd -u 10001 -m -s /bin/bash heurix

# Copy wheel from builder and install
COPY --from=builder /app/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && \
    rm -rf /tmp/*.whl && \
    find /usr/local/lib/python3.12 -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true && \
    find /usr/local/lib/python3.12 -type f -name "*.pyc" -delete

# Setup workspace mount target
USER heurix
WORKDIR /workspace

# Default entrypoint is hx CLI
ENTRYPOINT ["hx"]
CMD ["--help"]
