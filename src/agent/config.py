# src/agent/config.py — configuração via ambiente
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    data_dir: Path = Path("data")
    database_url: str | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"
    llamacpp_base_url: str | None = None
    api_host: str = "127.0.0.1"
    api_port: int = 8765

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        db_path = self.data_dir / "agent.db"
        return f"sqlite:///{db_path.resolve()}"


def get_settings() -> Settings:
    return Settings()
