FROM python:3.12-slim-bookworm

WORKDIR /app

# CPU only. pyopenjtalk may build OpenJTalk from source when no wheel matches.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential cmake \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/fetch_dict.sh /tmp/fetch_dict.sh
RUN chmod +x /tmp/fetch_dict.sh && /tmp/fetch_dict.sh

COPY app.py reading.py score.py ./

EXPOSE 8103
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8103"]
