import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    API_KEY: str = "my_instagram_scraper_secret_key_123"
    API_KEY_NAME: str = "X-API-Key"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    TIMEOUT_MS: int = 30000
    HEADLESS: bool = True

    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    VIEWPORT_WIDTH: int = 1280
    VIEWPORT_HEIGHT: int = 1000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

