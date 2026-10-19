# src/agent/config.py — configuração via ambiente
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    data_dir: Path = Path("data")
    database_url: str | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_timeout_sec: float = 600.0
    llamacpp_base_url: str = "http://127.0.0.1:8080"
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
    # Proteção contra recursão, não critério de decomposição: só para árvores que crescem sem fim.
    max_tree_depth: int = 16
    max_tasks_per_run: int = 400
    # Limites operacionais do run (0 desliga; `config.limits` sobrescreve por run). Atingido um deles, o run
    # pausa com diagnóstico e pode ser retomado; os contadores recomeçam na retomada.
    max_attempts_per_strategy: int = 3
    max_steps_without_progress: int = 60
    max_run_seconds: int = 14400
    max_model_calls_per_run: int = 400
    max_tool_calls_per_run: int = 600
    max_tokens_per_run: int = 5_000_000
    max_replans_per_run: int = 80
    # Observabilidade: o texto de cada campo de evento é truncado neste limite (a resposta final do modelo
    # usa o limite maior); fragmentos são agrupados por intervalo/tamanho; a fila de cada assinante SSE
    # que estoura vira um pedido de ressincronização. Cada conexão SSE dura no máximo `stream_max_seconds`
    # (o navegador reabre do último `seq`), senão o desligamento do servidor espera o stream para sempre.
    event_text_limit: int = 20_000
    event_output_limit: int = 200_000
    stream_delta_interval_ms: int = 120
    stream_delta_max_chars: int = 2_000
    stream_subscriber_queue: int = 1_000
    stream_ring_size: int = 3_000
    stream_max_seconds: float = 60.0
    shutdown_grace_seconds: float = 3.0
    static_web_dir: Path | None = None
    mcp_config_path: Path | None = None
    enable_background_worker: bool = True

    def resolved_database_url(self) -> str:
        # Pytest carrega o .env do projeto; sem isso os testes gravam no agent.db real.
        if os.environ.get("PYTEST_CURRENT_TEST"):
            self.data_dir.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{(self.data_dir / 'agent.db').resolve()}"
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
