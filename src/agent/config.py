"""
Arquivo: src/agent/config.py
Nome: config.py
Propósito: carregar a configuração do Callidus a partir do ambiente e do arquivo `.env`.
Responsabilidade: camada de configuração — parâmetros de ambiente, limites operacionais e caminhos de dados.
Componentes: Settings (modelo BaseSettings), get_settings().
Dependências: pydantic, pydantic-settings.
Observações: em testes, o banco é redirecionado para um SQLite temporário para não tocar o agent.db real.
"""
import os
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração do Callidus lida do ambiente e do arquivo `.env`.

    Atributos:
        data_dir: pasta raiz dos dados locais (banco, provedores, segredos).
        database_url: URL explícita do banco; quando ausente, é derivada de `data_dir`.
        default_provider / default_model_id: provedor e modelo usados quando a tarefa não os especifica.
        provider_timeout_sec / provider_max_retries / provider_allow_private_hosts / provider_verify_tls:
            política comum aos provedores HTTP.
        max_* e *_timeout_sec: limites operacionais (passos, tentativas, chamadas, tempo) do orquestrador.
        stream_* e event_*: limites de transporte e de truncamento dos eventos de observabilidade.

    Observações:
        Os limites protegem contra ciclos e rajadas; não definem o trabalho a ser feito.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    data_dir: Path = Path("data")
    database_url: str | None = None
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_timeout_sec: float = 600.0
    llamacpp_base_url: str = "http://127.0.0.1:8080"
    llamacpp_timeout_sec: float = 120.0
    default_provider: str = "ollama"
    default_model_id: str = "llama3.2"
    # Provedores: arquivo declarativo (YAML/JSON) com os provedores nomeados. Cada entrada tem
    # `type` (ollama, llamacpp, openai_compatible, openrouter, anthropic, gemini, mock) e as
    # opções do provedor; chaves vêm do ambiente por `api_key_env`.
    provider_config_path: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("PROVIDERS_CONFIG_PATH", "PROVIDER_CONFIG_PATH"),
    )
    # Política comum dos provedores HTTP: tempo limite, nº de tentativas em falha transitória
    # (só conexão recusada e 429), endereços privados permitidos (Ollama/llama.cpp locais) e TLS.
    provider_timeout_sec: float = 120.0
    provider_max_retries: int = 1
    provider_allow_private_hosts: bool = True
    provider_verify_tls: bool = True
    default_context_limit: int = 8192
    default_input_budget: int = 6000
    default_output_reserve: int = 1024
    use_generic_decomposition_template: bool = True
    allow_mock_fallback: bool = False
    # Limite de inferências de LLM simultâneas no processo (executor compartilhado).
    # 1 = execução estritamente sequencial, padrão do Callidus em máquinas modestas.
    # Servidores potentes podem subir o valor; a arquitetura não muda.
    max_concurrent_inferences: int = 1
    # Hierarquia de agentes: profundidade máxima da delegação, consultas pendentes por
    # agente e tentativas por consulta. Limites protegem de ciclos, não definem o trabalho.
    max_agent_depth: int = 16
    max_pending_queries_per_agent: int = 32
    max_query_attempts: int = 3
    # Tamanho máximo do contexto persistido de um agente (checkpoint). O estado estruturado
    # é preferível à transcrição; acima do limite, o agente guarda o resumo e os artefatos.
    max_agent_checkpoint_chars: int = 20_000
    # Tempo limite de uma operação do escalonador (uma etapa de run, uma consulta).
    agent_operation_timeout_sec: float = 300.0
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    max_attempts_per_task: int = 8
    max_orchestrator_steps: int = 100
    # Proteção contra recursão, não critério de decomposição: só para árvores que crescem sem fim.
    max_tree_depth: int = 16
    max_tasks_per_run: int = 400
    # Skills: quantas competências entram no prompt da operação e quanto do orçamento de
    # entrada elas podem ocupar (fração de `input_budget`).
    skills_max_per_operation: int = 2
    # Ciclo de ferramentas da operação: quantas rodadas o modelo pode usar para inspecionar o
    # projeto antes de devolver a alteração (cada rodada é uma chamada ao modelo).
    max_tool_iterations: int = 4
    # Total de chamadas de ferramenta no ciclo. Um modelo que pede muitas leituras por rodada
    # esgota as rodadas sem decidir; o orçamento de chamadas fecha essa porta.
    max_tool_calls: int = 8
    # Recuperação da verificação: quantas vezes uma verificação reprovada pode entrar no
    # ciclo diagnóstico → correção → re-verificação antes de a tarefa ser bloqueada.
    verification_max_recoveries: int = 2
    # Limites operacionais do run (0 desliga; `config.limits` sobrescreve por run). Atingido um deles, o run
    # pausa com diagnóstico e pode ser retomado. O consumo é cumulativo: a retomada não devolve o que
    # já foi gasto, ela concede `resume_limit_allowance` unidade(s) extra do limite base.
    max_attempts_per_strategy: int = 3
    # Teto do mesmo problema, com qualquer abordagem. É o limite externo da política de
    # tentativas: mesmo que cada repetição use uma abordagem diferente, o problema não pode
    # consumir o run inteiro. Relatório para a run pausar com diagnóstico.
    max_attempts_per_problem: int = 6
    max_steps_without_progress: int = 60
    max_run_seconds: int = 14400
    max_model_calls_per_run: int = 400
    max_tool_calls_per_run: int = 600
    max_tokens_per_run: int = 5_000_000
    # Faixas do orçamento acumulado e a reserva que implementação não pode gastar.
    # Aplicam-se ao teto autorizado da execução, não à janela de contexto do modelo.
    budget_warn_ratio: float = 0.70
    budget_reduce_ratio: float = 0.85
    budget_stop_ratio: float = 0.90
    budget_reserve_ratio: float = 0.10
    max_replans_per_run: int = 80
    # Unidades do limite base que cada retomada da run concede. A cota cresce a cada retomada,
    # mas o consumo já feito continua contando — a retomada destrava, não zera.
    resume_limit_allowance: int = 1
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
    # Runtime de automações dentro da API. O supervisor nativo (`callidus-supervisor`)
    # usa o mesmo núcleo e funciona sem a interface.
    enable_automation_supervisor: bool = True
    # Fuso padrão das automações criadas pelo chat. Sem esta configuração, o
    # interpretador temporal usa o fuso do Brasil (documentado no módulo).
    automation_timezone: str = "America/Sao_Paulo"
    # Segundos entre tiques do runtime de automações.
    automation_tick_seconds: float = 5.0
    # Teto de execuções de automação por tique (protege contra rajada de disparos).
    automation_max_executions_per_tick: int = 20
    # Ferramentas: famílias habilitadas e piso de risco que roda sem aprovação humana.
    # A lista de famílias habilitadas é o interruptor master das capacidades do agente
    # (sistema, desktop, engenharia, skills, navegador); deixar vazia significa "todas".
    tool_enabled_families: list[str] = []
    tool_disabled_families: list[str] = []
    # Nível de risco máximo que o agente executa sem pedir aprovação: `read`, `write`,
    # `execute`, `configure` ou `privileged`.
    tool_max_auto_risk: str = "write"
    # Ferramentas sempre liberadas, sem aprovação, mesmo acima do piso de risco.
    tool_always_allowed: list[str] = []
    # Ferramentas sempre bloqueadas, qualquer que seja o pedido.
    tool_never_allowed: list[str] = []
    # Estratégia linguística: `auto`, `native` ou `english_operational`.
    # `auto` usa inglês operacional só em pedido técnico que não está em inglês.
    # O idioma visível continua o do pedido, salvo `presentation_language` explícito.
    language_mode: str = "auto"
    presentation_language: str = "auto"

    def resolved_database_url(self) -> str:
        """URL do banco SQLite em uso, respeitando o isolamento dos testes.

        Returns:
            A URL SQLAlchemy do banco, já absoluta.

        Observações:
            Sob pytest, grava em um banco temporário (ou em `CALLIDUS_TEST_DATABASE_URL`);
            fora dos testes, usa `database_url` ou `data_dir/agent.db`.
        """
        # Pytest carrega o .env do projeto; sem isso os testes gravam no agent.db real.
        # O banco de teste é separado do banco de uso: escrever no agent.db real mistura
        # conversas de teste com as do usuário e destrói a trilha de auditoria.
        if os.environ.get("PYTEST_CURRENT_TEST"):
            override = os.environ.get("CALLIDUS_TEST_DATABASE_URL")
            if override:
                return override
            data_dir = Path(self.data_dir)
            if data_dir.resolve() == Path("data").resolve():
                # `data_dir` padrão: usa um banco temporário em vez do banco do usuário.
                import tempfile

                base = Path(tempfile.gettempdir()) / "callidus-tests"
                base.mkdir(parents=True, exist_ok=True)
                return f"sqlite:///{(base / 'agent-test.db').resolve()}"
            data_dir.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{(data_dir / 'agent.db').resolve()}"
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        db_path = self.data_dir / "agent.db"
        return f"sqlite:///{db_path.resolve()}"

    def resolved_provider_config_path(self) -> Path:
        """Arquivo de provedores em uso: o configurado ou, por padrão, `data/providers.yaml`."""
        if self.provider_config_path:
            return Path(self.provider_config_path)
        return Path(self.data_dir) / "providers.yaml"

    def resolved_secrets_dir(self) -> Path:
        """Pasta das credenciais gravadas pela interface (fora do versionamento)."""
        return Path(self.data_dir) / "secrets"


def get_settings() -> Settings:
    """Instância única de `Settings` com os caminhos derivados já preenchidos.

    Returns:
        As configurações carregadas, com `mcp_config_path` resolvido a partir de `data_dir`.

    Observações:
        A função não memoiza: cada chamada relê o ambiente, o que mantém os testes isolados.
    """
    s = Settings()
    if s.mcp_config_path is None:
        s.mcp_config_path = s.data_dir / "mcp.json"
    return s
