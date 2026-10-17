# src/agent/config.py — configuração via ambiente
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    data_dir: Path = Path("data")
    database_url: str | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"
    llamacpp_base_url: str | None = None
    default_provider: str = "ollama"
    default_model_id: str = "llama3.2"
    default_context_limit: int = 8192
    default_input_budget: int = 6000
    default_output_reserve: int = 1024
    use_generic_decomposition_template: bool = True
    allow_mock_fallback: bool = False
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    max_attempts_per_task: int = 8
    max_orchestrator_steps: int = 100
    static_web_dir: Path | None = None
    mcp_config_path: Path | None = None

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        db_path = self.data_dir / "agent.db"
        return f"sqlite:///{db_path.resolve()}"


def get_settings() -> Settings:
    s = Settings()
    if s.mcp_config_path is None:
        s.mcp_config_path = s.data_dir / "mcp.json"
    return s
