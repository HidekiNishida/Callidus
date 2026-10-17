# Agente de IA Local

Repositório **local git** do Project **Agente de IA Local**: documentação operacional, regras em `docs/` e **runtime do agente** (Python) para orquestrar trabalho de desenvolvimento com modelos locais pequenos.

## O que é este repo

| Camada | Função |
|--------|--------|
| **Este repositório** | Cópia de trabalho **versionada** (`git`): regras em `docs/`, ícones em `media/`, evidências e checklists em `internal/`. |
| **Cursor Project Context (Agent Store)** | Store sincronizado na nuvem, exposto no ambiente como `/cursor/stores/self/…` durante sessões do Project. |
| **`notes.md`** | Status efêmero do Project; pode divergir do painel **Notes** no Cursor. Preferir Notes do Project para status ao vivo; este arquivo é espelho de referência. |

## Como agentes devem usar

1. **Entrada:** [`docs/project-context.md`](/docs/project-context.md) → hub [`docs/regras/README.md`](/docs/regras/README.md).
2. **Convenção de links:** caminhos na raiz do repo com barra inicial — ex.: `/docs/regras/commits.md`, `/media/icons/hub.svg`, `/internal/tarefas/`.
3. **Tarefas:** criar/atualizar checklist em `internal/tarefas/` conforme [`docs/regras/checklists-tarefas.md`](/docs/regras/checklists-tarefas.md).
4. **Commits:** toda mudança coerente neste repo deve ser commitada em português ([`docs/regras/commits.md`](/docs/regras/commits.md)).

## Git vs Context — estratégia de sincronia

**Fonte da verdade para docs versionados:** este repositório local (`~/Documents/Projetos/Agente de IA Local/`).

| Fluxo | Quando usar |
|-------|-------------|
| **Trabalhar no repo → commit** | Edição normal: alterar arquivos aqui, validar links, `git commit`. Depois, copiar/sincronizar para o Agent Store do Project se o Context ainda for usado em Cloud Agents. |
| **Trabalhar no Context → espelhar no repo** | Se a mudança ocorreu só no store (`~/Library/Application Support/Cursor/AgentStores/…/files/`), trazer os arquivos para cá, reescrever links para a convenção `/docs/…` e commitar. |

Não há script de sync automático nesta fase; espelhamento manual ou tarefa futura.

## Estrutura

```text
docs/              regras, contexto e arquitetura (`docs/architecture/`)
src/agent/         núcleo: persistência, API, provedores, orquestrador
tests/             pytest
media/icons/       SVGs referenciados pelos docs
internal/          checklists e evidências (não normativas)
data/              SQLite e artefatos (gitignored; ver `.env.example`)
preferences.md     preferências do Project (coordenador)
notes.md           espelho de status; pode divergir do UI
```

## Executar o agente (API)

```bash
cd "~/Documents/Projetos/Agente de IA Local"
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # opcional
pytest
agente-api               # http://127.0.0.1:8765 — docs em /docs
```

Arquitetura e fases: [docs/architecture/visao-geral.md](/docs/architecture/visao-geral.md).

## Inicialização git

```bash
git log -1
```

Remote GitHub é opcional; o repositório foi criado apenas localmente.
