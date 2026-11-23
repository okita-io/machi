ARG BASE=nvcr.io/nvidia/pytorch:25.01-py3
FROM ${BASE}

WORKDIR /app

RUN pip install --no-cache-dir fastapi uvicorn pydantic "faster-whisper>=1.1.0"

COPY app.py ./

ENV ASR_ENGINE=kotoba-whisper-faster
EXPOSE 8101

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8101"]