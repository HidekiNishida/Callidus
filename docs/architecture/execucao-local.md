# Execução local

## Instalação

```bash
cd "~/Documents/Projetos/Agente de IA Local"
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Variáveis

| Variável | Padrão | Uso |
|----------|--------|-----|
| `AGENT_DATA_DIR` | `./data` | SQLite e artefatos |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Provedor Ollama |
| `LLAMACPP_BASE_URL` | — | Servidor OpenAI-compatible llama.cpp |

Copie `.env.example` para `.env` se necessário (nunca commitar secrets).

## API (Fase 1+)

```bash
agente-api
# ou: uvicorn agent.api.main:app --reload --port 8765
```

Endpoints iniciais: health, projetos, tarefas, transições de estado, eventos.

## Testes

```bash
pytest
```

Integrações com Ollama real ficam em testes marcados `@pytest.mark.integration` (opcionais).
