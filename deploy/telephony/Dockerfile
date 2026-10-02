FROM python:3.12-slim@sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 10001 voicebot
COPY requirements-telephony.lock.txt ./
RUN pip install --no-cache-dir -r requirements-telephony.lock.txt
COPY app/ ./app/
USER voicebot
CMD ["python", "-m", "app.worker", "start"]
