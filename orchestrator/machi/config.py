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

    hint_default_by_level: dict[int, int] = {1: 1, 2: 2, 3: 3, 4: 4}


settings = Settings()