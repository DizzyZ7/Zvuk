FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates tini && rm -rf /var/lib/apt/lists/*
COPY --from=node /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY . /app/
RUN pip install --no-cache-dir .
RUN useradd -r -m -u 10001 app && mkdir -p /shared && chown -R app:app /app /shared
USER app
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "app.main"]
