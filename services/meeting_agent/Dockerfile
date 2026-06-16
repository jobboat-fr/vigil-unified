# VIGIL meeting agent — the AI participant that joins live LiveKit rooms.
# Pinned Python (the OVH host runs 3.14, too new for the ML wheels).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY worker.py .

# Prefetch plugin models (silero VAD) so the first dispatched job is fast.
RUN python worker.py download-files || true

# Registers with LiveKit and waits for dispatch.
CMD ["python", "worker.py", "start"]
