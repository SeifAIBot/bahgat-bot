# NOTE: python:3.11-slim is not pinned to a digest here. Digest pinning is a
# follow-up (fetch the current digest from Docker Hub and pin it); no digest
# hash was invented for this file.
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg nodejs curl ca-certificates && rm -rf /var/lib/apt/lists/*
# nodejs is the yt-dlp JavaScript runtime (v1.8): yt-dlp enables only
# deno by default, so without a runtime the web client runs degraded
# (JS challenges unsolved -> bot-check). tools/youtube.py passes
# --no-js-runtimes --js-runtimes node on web-client attempts.
# curl is the WARP gate-check at runtime (v1.10): tools/warp.py curls
# cloudflare.com/cdn-cgi/trace through the proxy and needs warp=on.
# wgcf + wireproxy (v1.10): Cloudflare WARP egress so YouTube downloads
# work from Cloady's datacenter IP. Pinned versions, verified 2026-11-27
# in the VM (wgcf 2.3.1 is a static ELF; wireproxy 1.1.3 ships as a
# tarball holding a single `wireproxy` binary). -f makes curl fail the
# build loudly on a 404 instead of installing an HTML error page as a
# "binary"; the --help/--version smoke test catches a bad extract.
# Docker build itself is unverified locally (no Docker in the VM) —
# Cloady builds it on push.
RUN curl -fsSL -o /usr/local/bin/wgcf https://github.com/ViRb3/wgcf/releases/download/v2.3.1/wgcf_2.3.1_linux_amd64 \
 && curl -fsSL https://github.com/windtf/wireproxy/releases/download/v1.1.3/wireproxy_linux_amd64.tar.gz | tar -xz -C /usr/local/bin wireproxy \
 && chmod +x /usr/local/bin/wgcf /usr/local/bin/wireproxy \
 && wgcf --help >/dev/null && wireproxy --version
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
