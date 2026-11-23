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
# Dev/maintenance tools are not needed at runtime.
RUN grep -viE '^(git-filter-repo|gitpython|gitdb|smmap)==' requirements.txt > requirements.runtime.txt \
 && echo "flower==2.0.1" >> requirements.runtime.txt \
 && pip wheel --wheel-dir /wheels -r requirements.runtime.txt

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
 && groupadd --system app && useradd --system --gid app --home /app app

COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/* && rm -rf /wheels

WORKDIR /app
COPY --chown=app:app . .
COPY --chown=app:app docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh \
 && mkdir -p /app/f1_cache /app/logs /app/staticfiles \
 && chown -R app:app /app/f1_cache /app/logs /app/staticfiles

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/api/ > /dev/null || exit 1

ENTRYPOINT ["tini", "--", "entrypoint.sh"]
CMD ["uvicorn", "f1_project.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--log-level", "info"]
