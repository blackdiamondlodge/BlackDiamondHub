# Dockerfile

FROM python:3.12.9-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# psycopg2 build deps, plus a pg_dump that matches the production server
# (Postgres 16; Debian's own client is too old, so use the PGDG repo).
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev gcc libc6-dev curl ca-certificates && \
    install -d /usr/share/postgresql-common/pgdg && \
    curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
        https://www.postgresql.org/media/keys/ACCC4CF8.asc && \
    . /etc/os-release && \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends postgresql-client-17 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/

RUN python -m venv /app/.venv && \
    . /app/.venv/bin/activate && \
    pip install --upgrade pip && \
    pip install -r requirements.txt

COPY . /app/

# Collect static files for WhiteNoise. The key is only needed to import settings.
RUN . /app/.venv/bin/activate && \
    DJANGO_SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)" || exit 1

CMD ["/bin/bash", "/app/docker/entrypoint.sh"]
