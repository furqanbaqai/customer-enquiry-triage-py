# Use BuildKit's bundled frontend.
# Copyright 2026-2030 Openfintechlab, Inc. All rights reserved.
# Build and runtime must use the same Python minor version and Linux distribution.
ARG DOCKER_PYTHON_BUILDER_IMAGE=dhi.io/python:3.13-debian13-dev
ARG DOCKER_PYTHON_RUNTIME_IMAGE=dhi.io/python:3.13-debian13
FROM ${DOCKER_PYTHON_BUILDER_IMAGE} AS builder

USER 0
ENV APP_HOME=/app \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MQ_INSTALLATION_PATH=/opt/mqm \
    LD_LIBRARY_PATH=/opt/mqm/lib64:/opt/mqm/lib
WORKDIR /app

COPY --from=mq-binaries /10.0.0.5-IBM-MQC-Redist-LinuxX64.tar.gz /tmp/mq-client.tar.gz
RUN python3 -c "import tarfile; tarfile.open('/tmp/mq-client.tar.gz').extractall('/opt/mqm', filter='data')"
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
RUN python3 -m pip install uv
COPY . /app
# Explicitly use the image interpreter; never download Python under /root.
RUN uv sync --frozen --no-dev --python /usr/bin/python3
# Use the same interpreter path in the runtime and permit non-root reads/traversal.
RUN chmod -R a+rX /app /opt/mqm

FROM ${DOCKER_PYTHON_RUNTIME_IMAGE} AS runtime
ARG DOCKER_PYTHON_RUNTIME_IMAGE
LABEL "author"="openfintechlab.com" \
    "base-image-repo"="${DOCKER_PYTHON_RUNTIME_IMAGE}"
ENV APP_HOME=/app \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:/opt/mqm/bin:/usr/bin:/bin" \
    MQ_INSTALLATION_PATH=/opt/mqm \
    LD_LIBRARY_PATH=/opt/mqm/lib64:/opt/mqm/lib \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OFTL_RUN_MODE=WORKER
WORKDIR /app
COPY --from=builder /opt/mqm /opt/mqm
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/pyproject.toml /app/pyproject.toml
COPY --from=builder /app/prompts /app/prompts
USER 65532:65532
# Call main with an explicit mode; no shell, uv sync, or runtime downloads.
CMD ["/app/.venv/bin/python", "-c", "import os; from src.app import main; mode = os.environ['OFTL_RUN_MODE']; mode in ('CLIENT', 'WORKER') or __import__('sys').exit('OFTL_RUN_MODE must be CLIENT or WORKER'); main(mode)"]
