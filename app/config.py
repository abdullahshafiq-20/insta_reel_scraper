from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # API Security
    API_KEY: str = "my_instagram_scraper_secret_key_123"
    API_KEY_NAME: str = "X-API-Key"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Webhook
    WEBHOOK_URL: str = ""
    WEBHOOK_MAX_RETRIES: int = 5

    # Transcription
    TRANSCRIPTION_PROVIDER: str = "openai"  # "local" | "openai"
    OPENAI_API_KEY: str = ""
    OPENAI_TRANSCRIPTION_MODEL: str = "whisper-1"
    TRANSCRIPTION_COST_PER_MINUTE: float = 0.0045
    LOCAL_WHISPER_MODEL: str = "base"

    # Database & Redis
    POSTGRES_USER: str = "admin"
    POSTGRES_PASSWORD: str = "admin"
    POSTGRES_DB: str = "insta_reel_scraper"
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: str = "postgresql://admin:admin@postgres:5432/insta_reel_scraper"
    REDIS_URL: str = "redis://admin:admin123@redis:6379/0"
    DOCKER_NETWORK: str = "postgres-network"

    # Storage
    STORAGE_DIR: str = "./storage"
    CLEANUP_TEMP_FILES: bool = True

    # Scraper / Browser Pool
    TIMEOUT_MS: int = 30000
    HEADLESS: bool = True
    SCRAPE_BROWSER_POOL_SIZE: int = 3
    SCRAPE_REQUEST_JITTER_MIN_MS: int = 500
    SCRAPE_REQUEST_JITTER_MAX_MS: int = 2000

    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    VIEWPORT_WIDTH: int = 1280
    VIEWPORT_HEIGHT: int = 1000

    # Per-Stage Worker Concurrency
    N_SCRAPE_WORKERS: int = 3
    N_DOWNLOAD_WORKERS: int = 8
    N_AUDIO_WORKERS: int = 4
    N_LOCAL_WHISPER_WORKERS: int = 2
    N_OPENAI_WORKERS: int = 10
    N_WEBHOOK_WORKERS: int = 4

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
