# Checklist: Auditoria, padronização e manutenção da documentação

| Campo | Valor |
|-------|-------|
| Estado | concluída |
| Criado em | 2026-10-20 |
| Atualizado em | 2026-10-20 |
| Agente / tarefa | Auditoria documental completa, padrão visual e manutenção permanente |
| Regras consultadas | [Hub](/docs/regras/README.md) · [AGENTS.md](/AGENTS.md) · [documentacao.md](/docs/regras/documentacao.md) |

## Objetivo

Reformular a documentação do Callidus em qualidade, estrutura, navegação e consistência
visual, e tornar a manutenção documental **permanente** — com regra explícita e verificações
automatizadas, não com uma campanha de uma vez.

## Próxima ação

Nenhuma. A regra permanente está em [AGENTS.md](/AGENTS.md) (seção 12) e em
[documentacao.md](/docs/regras/documentacao.md); as verificações estão em `scripts/`.

## Etapas

- [x] Etapa 1 — Inventário: 85 documentos, 3 verificadores novos, 34 problemas estruturais
- [x] Etapa 2 — Padrão: categorias de ícone (emoji ↔ SVG), estrutura de página, precisão factual
- [x] Etapa 3 — Regras permanentes: seção "Documentação é parte da implementação" no AGENTS.md
- [x] Etapa 4 — Arquitetura documental: cabeçalhos de categoria em 78 documentos, índices atualizados
- [x] Etapa 5 — Conteúdo: contagens corrigidas (22 tabelas, 18 services, 23 docs), referências obsoletas
- [x] Etapa 6 — Validação: `check_docs`, `check_references`, `check_markdown`, `resume.py check`
- [x] Etapa 7 — Auditoria final: `resume.md` sincronizado (2087 itens carimbados), 675 testes passando

## Correções aplicadas

| Problema | Correção |
|----------|----------|
| Bloco de código sem fechar engolindo seções | `src/agent/services/README.md` — cerca de código adicionada |
| Bloco `markdown` com fence aninhado | `docs/regras/documentacao.md` — cercas ` ```` ` |
| 12 âncoras quebradas (números fora do slug) | `docs/architecture/automacoes.md` — TOC corrigido |
| 7 ícones com `aria-label` corrompido | `media/icons/*.svg` — rótulos em português |
| Contagens desatualizadas (14/17/20 tabelas) | README, `src/agent/README.md`, `persistence/README.md` |
| Referências a `_execute_task`/`_finalize_verification` | 6 documentos atualizados para `TaskExecutor`/`ModelOperation` |
| READMEs ausentes em 4 pastas de código | `automation/actions/`, `automation/service/`, `automation/triggers/`, `skills/catalog/` |
| `resume.md` com 1052 itens sem descrição | Preenchido a partir das docstrings do código (2087 itens carimbados) |
| 209 seções sem marcador de categoria | Emoji de categoria aplicado conforme o catálogo |
| Ícone de 48px no cabeçalho + `{width=48}` literal | Cabeçalho enxuto (título, propósito, volta); ícone só como marcador de 20px em índice, em HTML inline |

## Verificações

| Comando | Resultado |
|---------|-----------|
| `python scripts/check_docs.py` | nenhum link ou âncora quebrada |
| `python scripts/check_references.py` | todas as referências existem no código |
| `python scripts/check_markdown.py` | nenhum problema estrutural |
| `python scripts/resume.py check` | `resume.md` em dia |
| `python -m pytest -q` | 675 passed |

## Artefatos

| Path absoluto | Notas |
|---------------|-------|
| `/AGENTS.md` | Seção 12: documentação como parte da implementação |
| `/docs/regras/documentacao.md` | Padrão oficial: estrutura, marcadores, precisão, responsabilidade |
| `/docs/regras/ativos-visuais.md` | Catálogo dos 29 ícones (conjunto de regras + de categorias) |
| `/media/icons/*.svg` | Rótulos corrompidos corrigidos; conjunto de categoria **removido** (virou emoji) |
| `/scripts/check_markdown.py` | Estrutura Markdown, tabelas, blocos e diagramas |
| `/scripts/check_references.py` | Arquivos e símbolos citados existem |
| `/scripts/preencher_resume.py` | Preenche o `resume.md` a partir das docstrings do código |

## Notas de retomada

**Ajuste posterior (feedback do usuário):** o ícone no cabeçalho foi retirado — o
`{width=48}` é sintaxe que o Markdown padrão não entende (o renderizador mostra o atributo
ao lado da imagem) e um bloco colorido de 48px no topo de cada página pesa mais do que
ajuda. A categoria passou a ser marcada só pelo emoji da seção, e o SVG ficou como marcador
discreto (20px, HTML inline) dentro das tabelas de índice. Os 15 ícones de categoria foram
removidos; sobraram os 15 do conjunto de regras.

O `resume.md` passou de 2.660 para 5.434 linhas: ele agora cobre **todo** o inventário
(2.087 itens) e o `carimbar` voltou a funcionar — antes ele recusava gravar porque ~999 itens
não tinham descrição. Manter isso exige rodar `python scripts/resume.py check` junto com os
outros verificadores.