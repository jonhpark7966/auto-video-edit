"""Configuration management for AVID."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # Directories
    upload_dir: Path = Path("./uploads")
    output_dir: Path = Path("./outputs")
    temp_dir: Path = Path("./temp")

    # Whisper (for future use)
    whisper_model: str = "base"
    whisper_device: str = "auto"

    # Pipeline
    max_concurrent_jobs: int = 2

    def ensure_directories(self) -> None:
        """Create required directories if they don't exist."""
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)


# Global settings instance
settings = Settings()
