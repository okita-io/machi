# PyTorch CUDA runtime — Qwen3-TTS (Apache-2.0). Kokoro/Irodori can land in a follow-up.
FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    fastapi uvicorn pydantic pyyaml soundfile "qwen-tts>=0.1.1"

COPY app.py ./

ENV VOICES=/voices/voices.yaml
EXPOSE 8102

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8102"]