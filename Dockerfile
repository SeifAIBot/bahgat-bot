# NOTE: python:3.11-slim is not pinned to a digest here. Digest pinning is a
# follow-up (fetch the current digest from Docker Hub and pin it); no digest
# hash was invented for this file.
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN groupadd -r app && useradd -r -g app app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=app:app . .
USER app
# Polling bot + tiny stdlib health server (tg/health.py, GET /healthz on
# $PORT, default 8080). The heartbeat file written by tg/app.py
# (data/heartbeat.json, refreshed every 60s) is still the liveness signal;
# stale >5 min means the poll loop is dead. HEALTHCHECK below intentionally
# still reads the file (works even if the HTTP server itself is the broken
# part); Northflank probes /healthz instead.
HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
  CMD python -c "import json,time; d=json.load(open('/app/data/heartbeat.json')); assert time.time()-d['last_poll']<300"
CMD ["python", "main.py"]
