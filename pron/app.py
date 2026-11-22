from fastapi import FastAPI

app = FastAPI(title="Machi Pronunciation (stub)", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"status": "stub", "message": "Pronunciation scoring arrives in M2"}