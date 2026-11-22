import base64

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Machi ASR (CPU stub)", version="0.1.0")


class TranscribeRequest(BaseModel):
    text: str | None = None
    audio_b64: str | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "engine": "mock-cpu"}


@app.post("/v1/transcribe")
def transcribe(body: TranscribeRequest) -> dict:
    if body.text:
        return {"text": body.text, "confidence": 1.0, "source": "typed"}
    if body.audio_b64:
        _ = base64.b64decode(body.audio_b64)
        return {"text": "ふたりです", "confidence": 0.75, "source": "mock-audio"}
    return {"text": "", "confidence": 0.0, "source": "empty"}