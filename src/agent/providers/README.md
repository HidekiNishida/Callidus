# Provedores (`providers/`) — Ollama, llama.cpp, OpenRouter, OpenAI-compatível, Anthropic, Gemini, Mock

Abstração única de inferência: interface `LLMProvider`, perfis de modelo, capacidades declaradas,
streaming real e catálogo configurável. A camada não conhece skills, memória nem o ciclo do agente.

## Arquivos

| Arquivo | Classe / função | Propósito |
|---------|-----------------|-----------|
| [`base.py`](base.py) | `LLMProvider` (ABC), `ModelProfile`, `ChatCompletionRequest/Response`, `ChatMessage`, `ToolCall`, `ProviderCapabilities`, `ProviderHealth`, `ProviderError` e subclasses | **Contrato base** — `list_models()`, `chat()`, `chat_streaming()`, `capabilities()`, `health_check()` |
| [`http.py`](http.py) | `HttpClientConfig`, `validate_base_url`, `map_http_error`, `redact`, `get_json`, `post_json`, `stream_lines` | **Transporte comum** — tempo limite, TLS, sem redirecionamento, erros tipados, redação de segredos, retry só em falha transitória |
| [`registry.py`](registry.py) | `ProviderSpec`, `ProviderCatalog`, `load_catalog`, `build_provider`, `build_provider_by_name` | **Configuração declarativa** — arquivo YAML/JSON, interpolação `${VAR}`, fábrica de instâncias |
| [`ollama.py`](ollama.py) | `OllamaProvider` | **Ollama** (local ou remoto) — API nativa `/api/chat` + `/api/tags`, streaming linha a linha, `think` em modelos reasoning |
| [`llamacpp.py`](llamacpp.py) | `LlamaCppProvider` | **llama.cpp** (local ou remoto) — `llama-server` pela API compatível com OpenAI, streaming SSE, chave por cabeçalho ou arquivo |
| [`openai_compatible.py`](openai_compatible.py) | `OpenAICompatibleProvider` | **Adaptador reutilizável** para qualquer serviço no formato OpenAI (gateways, provedores compatíveis) |
| [`openrouter.py`](openrouter.py) | `OpenRouterProvider` | **OpenRouter** — herda do adaptador compatível com OpenAI, com URL padrão e cabeçalhos `X-Title` / `HTTP-Referer` |
| [`anthropic.py`](anthropic.py) | `AnthropicProvider` | **Anthropic** — Messages API nativa (`x-api-key`, prompt de sistema em campo próprio, blocos de conteúdo) |
| [`gemini.py`](gemini.py) | `GeminiProvider` | **Gemini** — `generateContent` nativo (`x-goog-api-key`, `contents`/`parts`, `generationConfig`) |
| [`mock.py`](mock.py) | `MockProvider` | Testes e execução offline — determinístico, sem rede |
| [`observed.py`](observed.py) | `observed_chat` | **Wrapper** — chama o provider + emite eventos no EventBus (`agent.started`, `agent.output.delta`, `agent.output.completed/failed`) |

## Interface Comum (`base.py`)

```python
class LLMProvider(ABC):
    name: str                    # "ollama" | "llamacpp" | "openrouter" | "anthropic" | "gemini" | "mock"
    supports_streaming: bool     # True se implementa chat_streaming real
    default_model: str | None    # modelo padrão do provedor

    def capabilities(self) -> ProviderCapabilities: ...
    async def list_models(self) -> list[str]: ...
    async def chat(self, request) -> ChatCompletionResponse: ...
    async def chat_streaming(self, request, on_delta): ...   # opcional
    async def health_check(self) -> ProviderHealth: ...       # conectividade sem inferência
    async def close(self) -> None: ...
```

`ProviderCapabilities` declara o que o provedor **realmente** oferece: `streaming`, `tools`,
`structured_output`, `vision`, `model_listing`, `usage_reporting`, `cancellation`. Recurso
ausente não é simulado: o pedido incompatível falha com `ProviderNotSupportedError`.

### Erros (`base.py`)

| Erro | Quando | Mensagem (marcos usados pela classificação de falhas) |
|------|--------|------------------------------------------------------|
| `ProviderError` | falha genérica | — |
| `ProviderConnectionError` | servidor recusou a conexão | “indisponível” |
| `ProviderTimeoutError` | tempo limite estourado | “tempo esgotado” |
| `ProviderAuthError` | 401/403 | “falha de autenticação” |
| `ProviderRateLimitError` | 429 | “limite de uso atingido” |
| `ProviderNotSupportedError` | recurso inexistente na API | — |
| `ProviderResponseError` | corpo ilegível | — |
| `ProviderConfigError` | URL/tipo/credencial de configuração inválidos | — |

## Recursos por provedor

| Provedor | Streaming | Ferramentas | JSON estruturado | Visão | Lista de modelos | Autenticação |
|----------|-----------|-----------|------------------|--------|------------------|--------------|
| Ollama | ✅ (JSON por linha) | ✅ | ✅ (`format`) | ✅ (`images`) | ✅ `/api/tags` | `Authorization: Bearer` (opcional) |
| llama.cpp | ✅ (SSE) | ✅ | ✅ (`response_format`) | ✅ | ✅ `/v1/models` | `Authorization: Bearer` ou `--api-key-file` |
| OpenAI-compatível | ✅ (SSE) | ✅ | ✅ (`json_schema`) | ✅ | ✅ `/models` | `Authorization: Bearer` |
| OpenRouter | ✅ (SSE) | ✅ | ✅ | ✅ | ✅ `/api/v1/models` (cache 5 min) | `Authorization: Bearer` |
| Anthropic | ✅ (SSE) | ✅ | ❌ | ✅ | ✅ `/v1/models` | `x-api-key` + `anthropic-version` |
| Gemini | ✅ (SSE `alt=sse`) | ✅ | ✅ (`responseSchema`) | ✅ | ✅ `/v1beta/models` (cache 5 min) | `x-goog-api-key` |
| Mock | ❌ | ❌ | ❌ | ❌ | ✅ (fixo) | — |

> O suporte real de ferramentas e JSON estruturado depende do **modelo** escolhido, não só do
> provedor. O Callidus não promete o que o modelo não faz.

## Configuração

Duas formas, que podem conviver:

1. **Variáveis de ambiente** (provedores embutidos): `OLLAMA_BASE_URL`, `LLAMACPP_BASE_URL`, `DEFAULT_PROVIDER`, `DEFAULT_MODEL_ID`.
2. **Arquivo de provedores** (`PROVIDERS_CONFIG_PATH`): provedores nomeados, escolhidos por nome no run.

```yaml
default_provider: ollama_remote

providers:
  ollama_local:
    type: ollama
    base_url: http://localhost:11434
    model: llama3.2

  ollama_remote:
    type: ollama
    base_url: ${CALLIDUS_OLLAMA_URL}
    model: qwen3:8b
    api_key_env: CALLIDUS_OLLAMA_API_KEY
    timeout: 60

  llama_cpp_remote:
    type: llamacpp
    base_url: ${CALLIDUS_LLAMA_CPP_URL}
    model: modelo-servidor
    api_key_env: CALLIDUS_LLAMA_CPP_KEY

  openrouter:
    type: openrouter
    base_url: https://openrouter.ai/api/v1
    model: autor/modelo-disponivel
    api_key_env: OPENROUTER_API_KEY

  gateway_interno:
    type: openai_compatible
    base_url: https://gateway.interno/v1
    model: modelo-do-gateway
    api_key_env: GATEWAY_API_KEY
    headers:
      X-Ambiente: producao
```

- `${VAR}` é substituída pelo valor do ambiente; `${VAR:-padrão}` usa um valor padrão.
  Variável ausente **sem** padrão é erro de configuração (o nome aparece, o valor nunca).
- Segredos vivem no ambiente (`api_key_env`) ou em arquivo (`api_key_file`), nunca no versionado.
- O exemplo completo está em [`providers.example.yaml`](../../../providers.example.yaml).

### Opções por provedor

| Opção | Vale para | Efeito |
|-------|-----------|--------|
| `type` | todos | `ollama`, `llamacpp`, `openai_compatible`, `openai`, `openrouter`, `anthropic`, `gemini`, `mock` |
| `base_url` | todos (obrigatório em `openai_compatible`) | Endereço do servidor |
| `model` | todos | Modelo padrão do provedor |
| `api_key_env` / `api_key_file` / `api_key` | todos | Origem da credencial |
| `timeout` | todos | Tempo limite da requisição (seg) |
| `headers` | todos | Cabeçalhos extras enviados |
| `max_retries` | todos | Tentativas extras em falha transitória (conexão recusada e 429) |
| `allow_private_hosts` | todos | `false` recusa host que resolve para endereço interno |
| `verify_tls` | todos | Desligar **não** é recomendado; existe para ambientes com certificado próprio |
| `models_cache_ttl` | OpenRouter, Gemini, compatível com OpenAI | Tempo de cache da lista de modelos (seg) |
| `referer` / `title` | OpenRouter | Cabeçalhos `HTTP-Referer` e `X-Title` |

## Seleção e troca de provedor

```python
# src/agent/orchestrator/runner.py
provider = _select_provider(settings, run_config)   # run_config["provider"] > catálogo > settings
profile = _profile_from_config(run_config, settings, provider)
```

Ordem de resolução do nome:

1. `run_config["provider"]` (o run escolhe).
2. `default_provider` do arquivo de provedores.
3. `DEFAULT_PROVIDER` das settings.
4. Provedores embutidos: `ollama`, `llamacpp`, `mock`.

Nome desconhecido é **erro explícito** (`ProviderConfigError`). Não há troca automática de provedor:
fallback silencioso mudaria custo, privacidade e qualidade da resposta. O mock só entra como
fallback quando `ALLOW_MOCK_FALLBACK=true` (opt-in explícito).

## Segurança

- Credenciais nunca são impressas: `redact()` remove a chave de mensagens de erro e de logs.
- TLS fica ligado (`verify_tls=true`); redirecionamento HTTP é desligado por padrão.
- URL base é validada (esquema `http`/`https`, host obrigatório, sem usuário/senha na URL).
- `allow_private_hosts=false` recusa host que resolve para endereço interno (SSRF); o padrão é
  `true` porque Ollama e llama.cpp legítimos rodam em `localhost` ou na rede interna.
- Retry só acontece em falha transitória **antes** de o servidor processar a requisição
  (conexão recusada e 429). Timeout e erro 5xx não são repetidos: podem custar inferência duplicada.

## Como registrar um novo adaptador

1. Crie `src/agent/providers/<nome>.py` com uma classe que herda de `LLMProvider`.
2. Implemente `list_models()` e `chat()`; `chat_streaming()` só se o serviço transmitir de verdade.
3. Declare `capabilities()` com o que a API realmente oferece.
4. Reutilize `HttpClientConfig`/`client_kwargs`/`get_json`/`post_json`/`stream_lines` para ter
   tempo limite, erros tipados, redação e retry sem duplicar lógica.
5. Registre o tipo em `PROVIDER_TYPES` e no `build_provider()` de [`registry.py`](registry.py).
6. Escreva os testes com `httpx.MockTransport` (sem rede, sem credencial real) e atualize a
   tabela de recursos acima e a documentação em [`docs/architecture/provedores.md`](../../../docs/architecture/provedores.md).

## Testes

```bash
pytest tests/test_providers_registry.py -v        # configuração declarativa
pytest tests/test_providers_selection.py -v        # seleção e troca
pytest tests/test_provider_security.py -v          # segredos, TLS, ausência de fallback
pytest tests/test_openai_compatible_provider.py -v # adaptador compatível com OpenAI
pytest tests/test_openrouter_provider.py -v        # OpenRouter
pytest tests/test_anthropic_provider.py -v         # Anthropic
pytest tests/test_gemini_provider.py -v             # Gemini
pytest tests/test_ollama_provider.py -v            # Ollama local e remoto
pytest tests/test_llamacpp_remote.py -v            # llama.cpp local e remoto
pytest tests/test_http_transport.py -v             # transporte, erros, redação
```

---

**Voltar:** [src/agent/README.md](../README.md) · **Raiz:** [README.md](../../../README.md) · **Documentação:** [provedores.md](../../../docs/architecture/provedores.md)
