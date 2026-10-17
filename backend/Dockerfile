# Backend image for Live Graph Agent Chat.
# Build context: repository root (COPY paths below start at backend/).
# Runtime env (.env / .env.test) is NOT baked in. The compose fragment (T3.8)
# passes it at container start via env_file.

FROM python:3.14.8-slim-trixie

# uv static binary, copied from its official image at an exact version pin.
COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:${PATH}" \
    HF_HOME=/app/.cache/huggingface

# Dedicated non-root user and group. No login shell, no home directory.
RUN groupadd --system appgroup \
    && useradd --system --gid appgroup --no-create-home --home-dir /app \
       --shell /usr/sbin/nologin appuser

WORKDIR /app

# Dependency layer first, so it is rebuilt only when the lock or pyproject changes.
# package = false in pyproject.toml, so this installs dependencies only.
# --locked fails the build if uv.lock does not match pyproject.toml.
# --no-dev leaves out pytest, ruff, mypy and httpx.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev

# Application code only. backend/tests, caches and any .env file are not copied.
COPY --chown=appuser:appgroup backend/app ./app

# /app itself must be writable by appuser so runtime paths such as uploads/
# under DATA_DIR can be created. The .venv stays root-owned and read-only.
RUN chown appuser:appgroup /app

# Pre-create the volume mount point (compose/backend.yml mounts lgac_backend_data
# here) owned by appuser. Docker initializes a fresh empty named volume's content
# and permissions from whatever already exists in the image at its mount path, so
# this is what makes /app/uploads (and the uploads/ subdir the app creates under
# DATA_DIR inside it) writable by the non-root user at runtime, not just at build time.
RUN mkdir -p /app/uploads && chown appuser:appgroup /app/uploads

# Same reasoning, for the local reranker's model-weights cache (compose/backend.yml
# mounts a volume here too): the BGE cross-encoder (app/models.py) downloads its
# weights from the HuggingFace Hub on first use, under HF_HOME above. Pre-create and
# chown it so that first download succeeds as appuser, and persists in the volume
# across container recreates instead of re-downloading every time.
RUN mkdir -p /app/.cache/huggingface && chown appuser:appgroup /app/.cache/huggingface

USER appuser

EXPOSE 8000

# Exec form. --workers 1 is a literal argument. Uvicorn lets an explicit
# command-line flag override UVICORN_WORKERS, so no environment variable
# can change the worker count. The app is single-process by design (D6).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
