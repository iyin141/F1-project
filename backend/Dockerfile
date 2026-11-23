# F1 Control Room API: web + Celery worker image.
# Builds on linux/amd64 and linux/arm64 (Oracle A1 Flex is aarch64).

ARG PYTHON_VERSION=3.13

# ---------------------------------------------------------------------------
# Stage 1: build wheels (compilers live only here)
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=f1_project.settings

RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl tini \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 1000 app && useradd --system --uid 1000 --gid app --home /home/app --create-home app

COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/* && rm -rf /wheels

# Optional: the `claude` CLI (headless LLM runner for the Stewards). Off by default.
# Node 20 from nodesource + the CLI pinned to the version verified locally.
# The host login is mounted at runtime (CLAUDE_CONFIG_DIR -> /home/app/.claude); no key is baked in.
ARG INSTALL_CLAUDE_CLI=0
ARG CLAUDE_CODE_VERSION=2.1.305
RUN if [ "$INSTALL_CLAUDE_CLI" = "1" ]; then       apt-get update       && apt-get install -y --no-install-recommends gnupg ca-certificates       && curl -fsSL https://deb.nodesource.com/setup_20.x | bash -       && apt-get install -y --no-install-recommends nodejs       && npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}       && rm -rf /var/lib/apt/lists/* ;     fi

WORKDIR /app
COPY --chown=app:app . .
COPY --chown=app:app docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh \
 && mkdir -p /app/f1_cache /app/logs /app/staticfiles \
 && chown -R app:app /app/f1_cache /app/logs /app/staticfiles

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/ > /dev/null || exit 1

ENTRYPOINT ["tini", "--", "entrypoint.sh"]
CMD ["uvicorn", "f1_project.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--log-level", "info"]
