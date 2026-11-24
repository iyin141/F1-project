# F1 Control Room API: web + Celery worker image.
# Builds on linux/amd64 and linux/arm64 (Oracle A1 Flex is aarch64).

ARG PYTHON_VERSION=3.13

# ---------------------------------------------------------------------------
# Stage 1: build wheels (compilers live only here)
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# No compilers: every pin has a cp313 manylinux wheel (amd64 and arm64) except pure-Python
# django-querycount (sdist). If CI's arm64 build ever needs a compiler, add build-essential here.

WORKDIR /build
COPY requirements.txt .
# Optional offline wheelhouse (git-ignored *.whl) for networks that corrupt long downloads:
#   pip download --only-binary=:all: --platform manylinux_2_28_x86_64 --python-version 3.13 \
#       --no-deps -d backend/wheelhouse -r backend/requirements.txt
# pip prefers it and falls back to PyPI for anything missing. BuildKit caches PyPI downloads.
COPY wheelhouse* /wheelhouse/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip wheel --no-index --find-links /wheelhouse --wheel-dir /wheels -r requirements.txt \
 || pip wheel --retries 10 --timeout 60 --find-links /wheelhouse --wheel-dir /wheels -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=f1_project.settings

# No apt here: psycopg2-binary bundles libpq, tini is replaced by compose `init: true`,
# and the healthcheck uses python instead of curl.
RUN groupadd --system --gid 1000 app \
 && useradd --system --uid 1000 --gid app --home /home/app --create-home app

COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/* && rm -rf /wheels

# Optional: Stewards embeddings (fastembed + ONNX, no torch). fastembed caps pillow<12, which the
# project pins, hence --no-deps (see requirements-rag.txt header). Off by default.
ARG INSTALL_RAG=0
COPY requirements-rag.txt /tmp/requirements-rag.txt
RUN if [ "$INSTALL_RAG" = "1" ]; then \
      pip install -r /tmp/requirements-rag.txt && pip install --no-deps fastembed==0.9.1 ; \
    fi \
 && rm /tmp/requirements-rag.txt

# Optional: the `claude` CLI (headless LLM runner for the Stewards). Off by default.
# Node 20 from nodesource + the CLI pinned to the version verified locally.
# The host login is mounted at runtime (CLAUDE_CONFIG_DIR -> /home/app/.claude); no key is baked in.
ARG INSTALL_CLAUDE_CLI=0
ARG CLAUDE_CODE_VERSION=2.1.305
RUN if [ "$INSTALL_CLAUDE_CLI" = "1" ]; then \
      apt-get update \
      && apt-get install -y --no-install-recommends curl gnupg ca-certificates \
      && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
      && apt-get install -y --no-install-recommends nodejs \
      && npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} \
      && rm -rf /var/lib/apt/lists/* ; \
    fi

WORKDIR /app
COPY --chown=app:app . .
COPY --chown=app:app docker/entrypoint.sh /usr/local/bin/entrypoint.sh
# /features, /models and /stewards/* are volume mount points: created app-owned so the
# named volumes inherit that ownership and the non-root user can write.
RUN chmod +x /usr/local/bin/entrypoint.sh \
 && mkdir -p /app/f1_cache /app/logs /app/staticfiles /features /models /stewards/models /stewards/data \
 && chown -R app:app /app/f1_cache /app/logs /app/staticfiles /features /models /stewards

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/', timeout=4)" || exit 1

ENTRYPOINT ["entrypoint.sh"]
CMD ["uvicorn", "f1_project.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--log-level", "info"]
