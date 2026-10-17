# Provedores LLM (`agent.providers`)

| Provedor | Arquivo | Uso padrão |
|----------|---------|------------|
| **Ollama** | [ollama.py](/src/agent/providers/ollama.py) | **Sim** (`DEFAULT_PROVIDER=ollama`) |
| llama.cpp | [llamacpp.py](/src/agent/providers/llamacpp.py) | Opcional (`LLAMACPP_BASE_URL`, padrão `http://127.0.0.1:8080`) |
| Mock | [mock.py](/src/agent/providers/mock.py) | Testes / demo e2e |

Contrato: [base.py](/src/agent/providers/base.py)

Voltar: [agent/README.md](/src/agent/README.md)
