from fastapi import FastAPI

app = FastAPI(title="Machi ASR (GPU stub)", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {
        "status": "stub",
        "message": "GPU ASR (Qwen3-ASR / kotoba-whisper) not wired in scaffold",
    }


@app.post("/v1/transcribe")
def transcribe() -> dict:
    return {"error": "not_implemented", "hint": "Use --profile cpu for demo"}