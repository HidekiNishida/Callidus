# Execução local

![configuracao](/media/icons/configuracao.svg){width=48}

Como instalar e executar o Callidus na própria máquina.

## ⚙️ Instalação

```bash
cd "~/Documents/Projetos/Callidus"
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # opcional
```

No **Python 3.14** o interpretador ignora `.pth` cujo nome começa com `_` (editable do setuptools/hatch) e também os `.pth` ocultos (`UF_HIDDEN`, comum no macOS). Depois do install:

```bash
python scripts/fix-python314-editable.py
python -c "import agent; print('OK')"
callidus-api
```

O script grava `callidus-src.pth` e cria o link `site-packages/agent` → `src/agent`. O link é o que garante o import: o importador do Python ignora a flag de ocultação, ao contrário do leitor de `.pth`.

Atalho sem o script: `PYTHONPATH=src callidus-api`

O script `agente-api` continua disponível como alias do `callidus-api`.

## 🧠 Padrões (documentação e runtime)

| Variável | Padrão | Efeito |
|----------|--------|--------|
| `DEFAULT_PROVIDER` | `ollama` | Runs sem config usam Ollama |
| `DEFAULT_MODEL_ID` | `llama3.2` | Modelo na decomposição |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | HTTP Ollama |
| `LLAMACPP_BASE_URL` | `http://127.0.0.1:8080` | Servidor llama.cpp (`llama-server`, API OpenAI em `/v1`) |
| `AGENT_DATA_DIR` | `./data` | SQLite + `mcp.json` |
| `ALLOW_MOCK_FALLBACK` | `false` | Testes podem habilitar |

Ordem de decomposição: **builtin e2e** (objetivo contém `e2e`) → **provedor escolhido** (Ollama ou llama.cpp) → template genérico → mock (se permitido).

## 🔌 API e UI

```bash
callidus-api
# http://127.0.0.1:8765/  — UI
# http://127.0.0.1:8765/docs
```

Demo sem Ollama: objetivo com `e2e` usa provider `mock` automaticamente na UI.

## 🧠 Conversas, memória e idioma

Cada projeto é um grupo de conversas. A pasta pode ficar em branco: nesse caso o agente usa a pasta do usuário do sistema. O botão **+** cria o projeto assim, e **Alterar pasta** troca o diretório depois, no projeto ou numa conversa. Uma conversa nova sem projeto também não pede pasta; usa a mesma pasta do usuário até alguém escolher outra. A ferramenta `system_info` informa sistema, usuário e essa pasta.

O menu de cada chat renomeia, troca a pasta, move para outro projeto ou remove. A memória da conversa acompanha a mudança de projeto; a memória do projeto fica na origem. Editar uma mensagem abre um ramo novo a partir dali, no estilo de duas continuações: o ramo antigo guarda o texto original e o que veio depois; o novo recomeça na mensagem editada. A memória do projeto vale para os dois. A memória da conversa segue o ramo e os ramos anteriores até o ponto da divisão; o que for gravado no ramo antigo depois da divisão não entra no novo.

A memória fica em dois escopos: do projeto inteiro e da conversa atual. Ao gravar, o texto completo permanece e um índice curto (resumo, fatos e tópicos) é guardado junto. Na hora de usar, o agente olha só esse índice, escolhe o que serve ao objetivo e só então quebra o texto das memórias escolhidas. O agente grava memória quando o pedido pede para lembrar, quando uma etapa usa a ferramenta `remember`, e ao concluir a conversa.

Se uma etapa para no meio com bloqueio ou falha, o orquestrador replaneja o que falta. O que já foi concluído permanece, o trecho ainda não iniciado do plano antigo é cancelado e entram etapas novas para seguir. Uma etapa que já é alteração, ferramenta ou verificação não é dividida de novo. Se o plano novo repete os títulos da etapa de cima, ela é executada e o chat marca o pensamento como igual, sem diferença. Pytest sem testes não recomeça quando o projeto já tem a entrega (página, estilo ou script). A mesma verificação que falha outra vez para, em vez de repetir até o limite. Uma inferência que estoura o tempo fica registrada como tentativa falha, com o motivo no chat, e entra na conta do limite, em vez de repetir sem deixar rastro. O modelo escolhido no compositor é o que executa: enviar a mensagem não devolve o seletor ao primeiro da lista. Cada resposta mostra o modelo daquela execução. A chamada pede a resposta direta, sem o raciocínio interno que consumia o tempo até estourar. Um pedido de página ou site não usa o plano de código Python: o agente escreve o HTML e confere o arquivo. O acompanhamento não altera a pasta do projeto; o ajuste fica no comportamento do agente, para os próximos projetos.

No chat aparece a resposta final, sem o relatório das etapas. Cada etapa e a execução mostram o tempo decorrido e os tokens gastos, cada um com um ícone; enquanto corre, o tempo avança, e ao terminar fica ao lado do horário, que tem o ícone de relógio. Os arquivos alterados ficam na resposta, com a quantidade de linhas adicionadas e removidas; o clique abre o diff. Links de referência http abrem o endereço. A data e a hora ficam como um horário curto ao lado do nome. Uma pergunta curta, sem pedido de alteração, recebe a resposta final direto. Se o modelo não escrever essa resposta, o fechamento ainda deixa um texto com a data local. Pensamentos, títulos de etapa e a resposta final seguem o idioma do pedido (português, inglês ou espanhol). Enquanto uma etapa roda, a mensagem do agente e o cartão da etapa ganham o brilho de tarefa em andamento.

A etapa aparece só com o título. O detalhe, inclusive o diff do arquivo editado, abre no clique. Se a última etapa estiver aberta, as próximas já chegam abertas; se ela estiver resumida, as próximas também ficam fechadas.

Quando a tarefa para no meio, o botão de resumo lista onde parou, o que foi feito e o que falta. Se a parada foi bloqueio ou falha, a instrução ganha um complemento para continuar sem refazer o que já passou.

O navegador no compositor tem três modos: desligado, invisível e janela. Ligado, a ferramenta `browser` pesquisa, abre páginas, lê, clica, digita e rola. A janela usa o Chrome instalado quando o Playwright está disponível.

## 🔌 MCP

```bash
cp data/mcp.example.json data/mcp.json
curl -X POST http://127.0.0.1:8765/mcp/discover
```

## 🧪 Testes

```bash
pytest
```

Índice de pastas: [readmes-pastas.md](/docs/regras/readmes-pastas.md).

Voltar: [architecture/README.md](/docs/architecture/README.md)