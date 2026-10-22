# Avaliação por área

A nota de cada área do Callidus, o que falta e a evidência por trás.

Voltar: [docs/progresso/](/docs/progresso/README.md) · Formato: [progresso.md](/docs/regras/progresso.md)

> **Revisado em:** 2026-10-21 · **Atualizado em:** 2026-10-21 · **Mudança:** major (criação)

Este documento é o **placar do projeto**. A medição do comportamento com o modelo real continua em [docs/architecture/avaliacao.md](/docs/architecture/avaliacao.md) (`lab/avaliar.py`); aqui ela vira nota por área.

## 📌 Resumo

O núcleo (pedido → plano → execução → verificação → resposta) funciona com o modelo local e passou em 15/15 cenários (*medido*). As áreas mais fracas são decomposição em repositório grande, recuperação de verificação, aprovação granular e desktop fora do macOS. Qualidade geral: **~61 %** (*estimado*, média simples das áreas).

## 📏 Como foi medido

- **Meta:** o que um desenvolvedor espera de um agente local que entrega trabalho verificado.
- **Do código** (commit `6868a30`, 2026-10-21, *medido*):

| Medida | Valor |
|--------|-------|
| Módulos Python em `src/` | 197 arquivos · 54 001 linhas |
| Interface (`web/static/assets/app/`) | 7 544 linhas de JavaScript |
| Rotas HTTP declaradas | 108 |
| Testes Python | 114 arquivos · 847 funções `test_` |
| Testes da interface | 57 passam (`node --test tests/web/*.test.mjs`) |
| Verificações de documentação | links, referências, Markdown, `resume.md`: passam |
| Documentos em `docs/` | 45 |

- **Registrado, não refeito agora:** 892 testes Python passaram no checkpoint de 2026-10-21 (`.cursor/CALLIDUS_CHECKPOINT.md`). A suíte não foi rodada nesta revisão: o ambiente da revisão não tinha Python ≥ 3.11 com as dependências.
- **Dos usuários:** nenhuma medição de uso real registrada.
- **Presença não é qualidade:** módulo que existe mas não foi exercitado com o modelo real não passa de 60 %.

## 📊 Áreas

| Área | Nota % | Faltando | Horas | Tipo |
|------|--------|----------|-------|------|
| Orquestração e verificação | 75 | [G3](/docs/progresso/gaps.md#g3-recuperação-quando-a-verificação-reprova) | 8 | estimado (aceite *medido*) |
| Decomposição e contexto | 55 | [G2](/docs/progresso/gaps.md#g2-decomposição-em-repositórios-grandes) | 16 | estimado |
| Interface (SPA) | 65 | [G5](/docs/progresso/gaps.md#g5-defeitos-conhecidos-do-feed), [G10](/docs/progresso/gaps.md#g10-streaming-de-tokens-na-interface) | 10 | estimado |
| Ferramentas e segurança | 60 | [G4](/docs/progresso/gaps.md#g4-aprovação-granular-de-ferramentas-arriscadas-na-ui) | 8 | estimado |
| Provedores | 70 | [G11](/docs/progresso/gaps.md#g11-paridade-entre-provedores) | 10 | estimado |
| Conhecimento, skills e hierarquia | 50 | [G7](/docs/progresso/gaps.md#g7-seleção-lexical-de-skills-estratégia-e-consulta), [G8](/docs/progresso/gaps.md#g8-grafo-de-conhecimento-multi-linguagem), [G9](/docs/progresso/gaps.md#g9-propagação-de-impacto-de-contratos) | 34 | estimado |
| Automações, sistema e desktop | 50 | [G12](/docs/progresso/gaps.md#g12-automação-de-desktop-nas-três-plataformas), [G15](/docs/progresso/gaps.md#g15-servidores-mcp-pesados) | 13 | estimado |
| Engenharia e documentação | 80 | [G6](/docs/progresso/gaps.md#g6-fiscais-automáticos-das-regras-de-engenharia), [G13](/docs/progresso/gaps.md#g13-versão-e-licença), [G14](/docs/progresso/gaps.md#g14-documentação-de-limitações-desatualizada) | 8 | estimado |
| Avaliação com o modelo real | 45 | [G1](/docs/progresso/gaps.md#g1-avaliação-real-ampla-e-repetível) | 10 | estimado |

## ⏱️ Calibração

Do `git log` (*estimado*): 113 commits entre 2026-10-17 e 2026-10-21, num intervalo somado de ~45 h entre o primeiro e o último commit de cada dia — **≈ 0,4 h por commit** no máximo. Use para conferir as horas da fila: um gap de 8 h equivale a ~20 commits do ritmo atual.

| Dia | Commits | Intervalo do dia |
|-----|---------|------------------|
| 2026-10-17 | 31 | 5,7 h |
| 2026-10-18 | 24 | 2,0 h |
| 2026-10-19 | 22 | 12,9 h |
| 2026-10-20 | 25 | 12,4 h |
| 2026-10-21 | 11 | 12,1 h |

## 🚫 Fora de escopo

- Serializar inferência entre processos ([limitacoes.md](/docs/architecture/limitacoes.md), item 3).
- Serviço em nuvem obrigatório: o Callidus é local por desenho.

## 🔎 Evidências por área

| Área | Arquivos e testes |
|------|-------------------|
| Orquestração e verificação | `src/agent/orchestrator/`, `tests/test_e2e_orchestrator.py`, `tests/test_independent_verification.py`, `tests/test_global_acceptance.py` |
| Decomposição e contexto | `src/agent/context/`, `tests/test_hierarchical_decompose.py`, `tests/test_context_budget.py` |
| Interface | `web/static/assets/app/`, `tests/web/`, `tests/test_web_frontend.py` |
| Ferramentas e segurança | `src/agent/tools/`, `src/agent/security/`, `tests/test_tool_contracts.py`, `tests/test_provider_security.py` |
| Provedores | `src/agent/providers/`, `tests/test_ollama_provider.py`, `tests/test_openai_compatible_provider.py` |
| Conhecimento, skills e hierarquia | `src/agent/knowledge/`, `src/agent/skills/`, `tests/test_knowledge_graph.py`, `tests/test_agent_hierarchy_e2e.py` |
| Automações, sistema e desktop | `src/agent/automation/`, `src/agent/desktop/`, `tests/test_automation_end_to_end.py`, `tests/test_desktop_automation.py` |
| Engenharia e documentação | `scripts/ci.py`, `scripts/check_docs.py`, `scripts/resume.py`, [AGENTS.md](/AGENTS.md) |
| Avaliação com o modelo real | `lab/avaliar.py`, [docs/architecture/avaliacao.md](/docs/architecture/avaliacao.md) |

## 🕑 Histórico de revisão

| Data | Mudança | Resumo |
|------|---------|--------|
| 2026-10-21 | major | Criação: contagens medidas no commit `6868a30`, notas estimadas por área |
