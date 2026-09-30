FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# curl is required: Coolify's own container healthcheck needs curl/wget.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 10001 voicebot

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Build context is this directory (Coolify: set base directory to
# voicebot/, or push voicebot/ as the repo root).
COPY app/ ./app/

USER voicebot
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT','8000')}/health\", timeout=4)"

CMD ["sh", "-c", "exec uvicorn app.server:create_app --factory --host 0.0.0.0 --port ${PORT}"]
