from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    bot_token: str
    gemini_api_key: str
    hf_token: str = ""  # Hugging Face token for Flux
    cryptobot_token: str = ""  # @CryptoBot API token
    admin_ids: str = ""  # comma-separated TG IDs

    telegram_api_id: str = ""
    telegram_api_hash: str = ""
    local_bot_api_url: str = ""
    local_bot_api_data: Path = Path("./bot-api-data")

    temp_dir: Path = Path("./temp")
    max_video_size_mb: int = 2000
    max_video_duration: int = 600  # seconds

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
settings.temp_dir.mkdir(parents=True, exist_ok=True)
