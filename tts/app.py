from fastapi import FastAPI

app = FastAPI(title="Machi TTS (GPU stub)", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {
        "status": "stub",
        "message": "GPU TTS (Qwen3-TTS / Irodori) not wired in scaffold",
    }


@app.post("/v1/synthesize")
def synthesize() -> dict:
    return {"error": "not_implemented", "hint": "Use --profile cpu for demo"}