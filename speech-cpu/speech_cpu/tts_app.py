import base64
import struct
import wave
from io import BytesIO

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Machi TTS (CPU stub)", version="0.1.0")


class SynthesizeRequest(BaseModel):
    text: str
    voice: str = "npc"


def _stub_wav(seconds: float = 0.35, hz: int = 440) -> bytes:
    sample_rate = 24000
    n = int(sample_rate * seconds)
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for i in range(n):
            val = int(8000 * (1 if (i // (sample_rate // hz)) % 2 == 0 else -1))
            wf.writeframes(struct.pack("<h", val))
    return buf.getvalue()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "engine": "stub-wav"}


@app.post("/v1/synthesize")
def synthesize(body: SynthesizeRequest) -> dict:
    wav = _stub_wav()
    return {
        "text": body.text,
        "voice": body.voice,
        "audio_b64": base64.b64encode(wav).decode("ascii"),
        "format": "wav",
    }