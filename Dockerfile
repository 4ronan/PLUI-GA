FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN mkdir -p /app/output /data/cache \
    && useradd --uid 10001 --create-home appuser \
    && chown -R appuser:appuser /app /data

USER appuser
ENV PYTHONUNBUFFERED=1 \
    PORT=8765 \
    DIAG_CACHE_DIR=/data/cache \
    DIAG_CACHE_TTL_HOURS=24 \
    DIAG_JOB_QUEUE_LIMIT=20 \
    DIAG_RATE_LIMIT_PER_MINUTE=10

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8765')+'/api/ready',timeout=3).read()"

CMD ["python", "scripts/diagnostic_web_server.py"]
