# Execução local

## Instalação

```bash
cd "~/Documents/Projetos/Agente de IA Local"
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # opcional
```

No **Python 3.14** o interpretador ignora `.pth` cujo nome começa com `_` (editable do setuptools/hatch). Depois do install:

```bash
python scripts/fix-python314-editable.py
python -c "import agent; print('OK')"
agente-api
```

Atalho sem o script: `PYTHONPATH=src agente-api`

## Padrões (documentação e runtime)

| Variável | Padrão | Efeito |
|----------|--------|--------|
| `DEFAULT_PROVIDER` | `ollama` | Runs sem config usam Ollama |
| `DEFAULT_MODEL_ID` | `llama3.2` | Modelo na decomposição |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | HTTP Ollama |
| `LLAMACPP_BASE_URL` | `http://127.0.0.1:8080` | Servidor llama.cpp (`llama-server`, API OpenAI em `/v1`) |
| `AGENT_DATA_DIR` | `./data` | SQLite + `mcp.json` |
| `ALLOW_MOCK_FALLBACK` | `false` | Testes podem habilitar |

Ordem de decomposição: **builtin e2e** (objetivo contém `e2e`) → **provedor escolhido** (Ollama ou llama.cpp) → template genérico → mock (se permitido).

## API e UI

```bash
agente-api
# http://127.0.0.1:8765/  — UI
# http://127.0.0.1:8765/docs
```

Demo sem Ollama: objetivo com `e2e` usa provider `mock` automaticamente na UI.

## Conversas, memória e idioma

Cada projeto é a pasta do código. Dentro dele, cada conversa é um chat separado. A barra lateral lista essas conversas; o botão **+** abre um navegador de pastas (e, no macOS, o Finder).

A memória fica em dois escopos: do projeto inteiro e da conversa atual. Ao gravar, o texto completo permanece e um resumo curto é guardado junto. Ao entrar no contexto de uma etapa, esse texto é quebrado e só os trechos ligados ao objetivo entram no prompt. O agente grava memória quando o pedido pede para lembrar, quando uma etapa usa a ferramenta `remember`, e ao concluir a conversa.

Pensamentos, títulos de etapa e a resposta final seguem o idioma do pedido (português, inglês ou espanhol). Enquanto uma etapa roda, a mensagem do agente e o cartão da etapa ganham o brilho de tarefa em andamento.

A etapa aparece só com o título. O detalhe, inclusive o diff do arquivo editado, abre no clique. Se a última etapa estiver aberta, as próximas já chegam abertas; se ela estiver resumida, as próximas também ficam fechadas.

Quando a tarefa para no meio, o botão de resumo lista onde parou, o que foi feito e o que falta. Se a parada foi bloqueio ou falha, a instrução ganha um complemento para continuar sem refazer o que já passou.

O navegador no compositor tem três modos: desligado, invisível e janela. Ligado, a ferramenta `browser` pesquisa, abre páginas, lê, clica, digita e rola. A janela usa o Chrome instalado quando o Playwright está disponível.

## MCP

```bash
cp data/mcp.example.json data/mcp.json
curl -X POST http://127.0.0.1:8765/mcp/discover
```

## Testes

```bash
pytest
```

Índice de pastas: [readmes-pastas.md](/docs/regras/readmes-pastas.md).

Voltar: [architecture/README.md](/docs/architecture/README.md)
