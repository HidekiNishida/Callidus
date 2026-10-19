# Provedores (`providers/`) — Ollama, llama.cpp, Mock + Interface Comum

Abstração unificada para inferência: interface `LLMProvider`, perfis de modelo, streaming real e fallback para testes.

## Arquivos

| Arquivo | Classe | Propósito |
|---------|--------|-----------|
| [`base.py`](base.py) | `LLMProvider` (ABC), `ModelProfile`, `ChatCompletionRequest/Response`, `ChatMessage`, `ProviderError` | **Contrato base** — `list_models()`, `chat()`, `chat_streaming()` (opcional) |
| [`ollama.py`](ollama.py) | `OllamaProvider` | **Padrão** — HTTP `/api/chat` + `/api/tags`, streaming real (line-delimited JSON), `think` para modelos reasoning |
| [`llamacpp.py`](llamacpp.py) | `LlamaCppProvider` | llama.cpp server (OpenAI-compat `/v1/chat/completions`), streaming SSE |
| [`mock.py`](mock.py) | `MockProvider` | Testes/demo — `keyword_map` → resposta canned |
| [`observed.py`](observed.py) | `observed_chat` | **Wrapper** — chama provider + emite eventos streaming no EventBus (`agent.started`, `agent.output.delta`, `agent.output.completed/failed`) |

## Interface Comum (`base.py`)

```python
class LLMProvider(ABC):
    name: str                    # "ollama" | "llamacpp" | "mock"
    supports_streaming: bool     # True se implementa chat_streaming real

    @abstractmethod
    async def list_models(self) -> list[str]: ...
    
    @abstractmethod
    async def chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse: ...
    
    async def chat_streaming(self, request, on_delta):  # opcional
        raise NotImplementedError

class ModelProfile(BaseModel):
    model_id: str
    context_limit: int = 8192
    input_budget: int = 6000
    output_reserve: int = 1024
    supports_tools: bool = False
    supports_vision: bool = False
    generation: dict = {}  # temperature, top_p, num_predict, think, etc.
```

## Ollama Provider (`ollama.py`)

```python
provider = OllamaProvider(base_url="http://127.0.0.1:11434", timeout=600.0)
models = await provider.list_models()  # GET /api/tags

# Chat não-streaming
resp = await provider.chat(ChatCompletionRequest(
    messages=[ChatMessage(role="user", content="...")],
    profile=ModelProfile(model_id="llama3.2", generation={"temperature": 0.7})
))
# resp.content, resp.prompt_tokens_estimate, resp.completion_tokens_estimate

# Streaming real (line-delimited JSON)
resp = await provider.chat_streaming(request, on_delta=lambda chunk: print(chunk, end=""))
```

**Recursos**:
- `think` automático para modelos reasoning (`qwen3`, `gpt-oss`, `deepseek`, `reason`)
- `format` para `response_format` (JSON schema)
- Timeout configurável (padrão 600s)
- Uso de tokens via `prompt_eval_count` / `eval_count` (Ollama não usa padrão OpenAI `usage`)

## llama.cpp Provider (`llamacpp.py`)

```python
provider = LlamaCppProvider(base_url="http://127.0.0.1:8080")
# Requer llama-server com API OpenAI compatível em /v1
```

**Recursos**:
- Streaming via SSE (`/v1/chat/completions` com `stream: true`)
- Uso de tokens via `usage.prompt_tokens` / `usage.completion_tokens` (padrão OpenAI)

## Mock Provider (`mock.py`)

```python
provider = MockProvider(keyword_map={
    "e2e": "resposta para demo e2e",
    "calculadora": "def add(a, b): return a + b",
})
# Útil para testes E2E sem modelo real
```

## Factory + Profile (Usado pelo Orquestrador)

```python
# orchestrator/runner.py
def _select_provider(settings, run_config) -> LLMProvider:
    name = run_config.get("provider") or settings.default_provider  # "ollama"
    if name == "ollama": return OllamaProvider(settings.ollama_base_url, settings.ollama_timeout_sec)
    if name == "llamacpp": return LlamaCppProvider(settings.llamacpp_base_url)
    return MockProvider()

def _profile_from_config(run_config, settings) -> ModelProfile:
    model_id = run_config.get("model_id") or settings.default_model_id
    vision = any(tok in model_id.lower() for tok in ("-vl", "vl:", "vision", "llava", "moondream"))
    return ModelProfile(
        model_id=model_id,
        context_limit=run_config.get("context_limit", settings.default_context_limit),
        input_budget=run_config.get("input_budget", settings.default_input_budget),
        output_reserve=run_config.get("output_reserve", settings.default_output_reserve),
        supports_vision=vision,
        generation=run_config.get("generation", {"think": False}),
    )
```

## Observed Chat (Streaming no EventBus)

```python
# orchestrator/runner.py → _execute_task
from agent.providers.observed import observed_chat

resp = await observed_chat(
    provider,
    ChatCompletionRequest(messages=budget.messages, profile=profile),
    purpose="operation",           # "operation" | "plan" | "final_answer"
    stream=stream_allowed,         # False se meta.stream=False ou run_config.stream=False
)

# Emite no EventBus (observability/bus.py):
# agent.started {output_id, task_id, agent, provider, model, streaming, purpose}
# agent.output.delta {output_id, text}  (batched por DeltaBatcher)
# agent.output.completed/failed {output_id}
```

## Ordem de Decomposição (Orquestrador)

1. **Builtin E2E** — objetivo contém `e2e` ou `calc.py`
2. **Direct Answer** — pergunta curta sem alteração
3. **Modelo Escolhido** — Ollama (padrão) ou llama.cpp via `plan_with_model`
4. **Template Genérico** — 3 etapas fixas (inspecionar → aplicar → verificar)
5. **Mock Fallback** — se `ALLOW_MOCK_FALLBACK` ou provider=mock

## Configuração (Settings)

| Variável | Padrão | Efeito |
|----------|--------|--------|
| `DEFAULT_PROVIDER` | `ollama` | Provider usado quando run não especifica |
| `DEFAULT_MODEL_ID` | `llama3.2` | Modelo na decomposição e operações |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Endpoint Ollama |
| `OLLAMA_TIMEOUT_SEC` | `600` | Timeout inferência (seg) |
| `LLAMACPP_BASE_URL` | `http://127.0.0.1:8080` | llama.cpp server |
| `ALLOW_MOCK_FALLBACK` | `false` | Permite mock se modelo falhar |

## Testes

```bash
# Provider Ollama (requer Ollama rodando)
pytest tests/test_llamacpp_provider.py -v

# Modelo choice (UI + API)
pytest tests/test_model_choice.py -v

# E2E com mock
pytest tests/test_e2e_orchestrator.py -v
```

---

**Voltar:** [src/agent/README.md](../README.md) · **Raiz:** [README.md](../../../README.md) · **Execução local:** [docs/architecture/execucao-local.md](../../../docs/architecture/execucao-local.md)