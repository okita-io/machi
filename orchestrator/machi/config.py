from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_base_url: str = ""
    llm_model: str = "default"
    llm_api_key: str = "none"

    asr_url: str = "http://speech-cpu:8101"
    tts_url: str = "http://speech-cpu:8102"

    scenarios_path: str = "/scenarios"
    db_path: str = "/data/machi.sqlite"
    assets_base_url: str = "http://assets:8080"
    # Directory with baked NPC audio under audio/{scenario_id}/. Empty disables the cache.
    assets_path: str = "/assets"

    # Hands-free only. Push-to-talk does not read these.
    vad_enabled: bool = True
    vad_model_path: str = ""
    vad_silence_ms: int = 500
    vad_candidate_ms: int = 250
    vad_threshold: float = 0.5
    vad_require_speech: bool = True

    # Optional. Default image has no torch/transformers. Heuristic scorer otherwise.
    smart_turn_enabled: bool = False
    smart_turn_model: str = "pipecat-ai/smart-turn-v3"
    smart_turn_filename: str = "smart-turn-v3.2-cpu.onnx"
    smart_turn_model_path: str = ""
    smart_turn_threshold: float = 0.5

    hint_default_by_level: dict[int, int] = {1: 1, 2: 2, 3: 3, 4: 4}


settings = Settings()