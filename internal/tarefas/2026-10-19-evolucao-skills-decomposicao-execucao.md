# Checklist: Evolução do Agente Local — Skills, Prompt Estratégico, Decomposição Recursiva e Execução Profissional

![tarefas](/media/icons/tarefas.svg){width=48}

| Campo | Valor |
|-------|-------|
| Estado | concluída |
| Criado em | 2026-10-19 |
| Atualizado em | 2026-10-19 |
| Agente / tarefa | Engenharia completa: Skills, Estratégia Profissional, Decomposição Recursiva, Integridade e Verificação |
| Regras consultadas | [Hub](/docs/regras/README.md), [principios.md](/docs/regras/principios.md), [validacoes-testes.md](/docs/regras/validacoes-testes.md), [commits.md](/docs/regras/commits.md), [verificacao-final.md](/docs/regras/verificacao-final.md), [resumo-projeto.md](/docs/regras/resumo-projeto.md), [readmes-pastas.md](/docs/regras/readmes-pastas.md), [checklists-tarefas.md](/docs/regras/checklists-tarefas.md) |

## 🎯 Objetivo

Evoluir a arquitetura do Callidus de ponta a ponta: integrar sistema de Skills reutilizáveis sob demanda, camada de definição de abordagem profissional e estratégia executável, decomposição hierárquica recursiva e adaptativa com limites seguros, integridade rigorosa de estados/consolidação/conclusão com suporte a subtarefas opcionais e falhas parciais, verificação independente multicritério e controle fino de tokens e observabilidade.

## Próxima ação

Nenhuma — tarefa concluída. Evolução futura sugerida: cache do catálogo de skills por `mtime` e estratégias de verificação alternativa na recuperação.

## 🔄 Etapas

- [x] Descoberta, auditoria e linha de base (218 testes existentes validados e corrigidas regressões preexistentes)
- [x] Matriz de requisitos e mapeamento de lacunas arquiteturais
- [x] Módulo de Skills (`src/agent/skills/`): modelos, catálogo, descoberta, carregamento sob demanda, contrato e testes
  - `SkillSpec`/`SkillMatch` (`models.py`), registro com precedência (`discovery.py`), seleção econômica (`selector.py`), builtins offline (`builtins.py`)
  - Catálogo Markdown como fonte de verdade: `src/agent/skills/catalog/loader.py` + `skills/*.md` com metadados completos
- [x] Camada de Abordagem Profissional e Estratégia (`src/agent/orchestrator/strategy.py`): preservação de intenção original, especialidades dinâmicas, análise de riscos e critérios de aceitação
  - `ProfessionalStrategy` (+ `complexity_rank`, `needs_atomization`, `from_dict`) e `ProfessionalStrategist.analyze()`
  - Integração no `RunOrchestrator` (evento `strategy.formulated`) e herança da estratégia pelos filhos
- [x] Decomposição Hierárquica Recursiva e Adaptativa (`src/agent/orchestrator/decomposition.py`, `atomizer.py`, `runner.py`): subdecomposição de etapas internas complexas, limites de profundidade/tarefas, prevenção de ciclos
  - `adaptive_decompose_operation()` com trilhas por domínio, `depth_guard()`, `max_depth` e auto-dependência ignorada em `apply_decomposition()`
- [x] Integridade da Execução e Consolidação Semântica (`state_machine.py`, `consolidation.py`, `global_verify.py`): distinção obrigatório vs opcional, bloqueio por dependência falha, conclusão orientada a requisitos
  - `is_optional()` no consolidador, falha opcional → conclusão com ressalvas, dependência opcional não bloqueia
- [x] Verificação Independente e Recuperação (`verification/runner.py`, `verification/recovery.py`): novos verificadores (linter/estático), ciclo diagnóstico -> correção -> re-verificação
  - Verificadores `file_exists` e `static_analysis`; `diagnose_verification_failure()` + `plan_recovery()` com limite de recuperações
- [x] Orçamento de Tokens e Compatibilidade (`context/operation_builder.py`, `context/budget.py`): injeção seletiva de Skills e estratégias sem estourar limite do modelo
  - Componente `skills` (prioridade 75, opcional) limitado a 12% do `input_budget`; orientação de recuperação no bloco de falhas
- [x] Observabilidade em tempo real: eventos para estratégia, skills ativadas, decomposição recursiva
  - `strategy.formulated`, `skill.selected`, `decomposition.recursive`, `verification.recovery_planned`
- [x] Catálogo de Skills e Agentes especializados em `skills/` e `src/agent/skills/catalog/`
- [x] Testes integrados e avaliação comparativa (tarefa simples vs multinível, falha de skill, falha opcional vs obrigatória, esgotamento de orçamento)
  - `tests/test_skills_catalog.py`, `tests/test_skills_evaluation.py`, `tests/test_skills_observability.py`, `tests/test_strategy_and_decomposition.py`
- [x] Atualização do `Resume.md` e sincronia com `scripts/resume.py check` (1172 itens carimbados)
- [x] Documentação arquitetural atualizada
  - `docs/architecture/skills-estrategia.md` (novo) + hub, visão geral, limitações, README raiz e READMEs de pasta
- [x] Commits lógicos organizados no Git
- [x] Verificação final: código ↔ docs ↔ checklists ↔ regras ([verificacao-final.md](/docs/regras/verificacao-final.md))

## Bloqueios

- Nenhum no momento.

## Artefatos

| Path absoluto | Notas |
|---------------|-------|
| `/src/agent/skills/` | Módulo de skills: contrato, catálogo, descoberta e seleção |
| `/src/agent/skills/catalog/loader.py` | Leitura do catálogo Markdown (fonte de verdade) |
| `/skills/` | Catálogo editável de skills (6 competências profissionais) |
| `/src/agent/orchestrator/strategy.py` | Camada de abordagem profissional e estratégia executável |
| `/src/agent/verification/recovery.py` | Ciclo diagnóstico → correção → re-verificação |
| `/docs/architecture/skills-estrategia.md` | Documento de arquitetura da evolução |
| `/tests/test_skills_catalog.py` | Testes do catálogo e da precedência |
| `/tests/test_skills_evaluation.py` | Avaliação comparativa dos cenários |
| `/tests/test_skills_observability.py` | Testes de integração dos eventos |
| `/internal/tarefas/2026-10-19-evolucao-skills-decomposicao-execucao.md` | este checklist |

## Notas de retomada

Linha de base: 218 testes passam em 11.68s.
Regressões corrigidas no baseline:
1. `src/agent/api/observe_routes.py`: terminal status check e cursor rotation com `max_age` e `last_event_id` restaurados.
2. `src/agent/observability/sanitize.py`: função `truncate` ajustada para manter estritamente o limite de caracteres enquanto preserva o marcador de caracteres omitidos.
3. `tests/test_conversations_memory_i18n.py`: fixture segura para `/fs/browse` no sandbox.

Retomada: 255 testes passam (7,68s). `python3 scripts/resume.py check` → "resume.md em dia" (1172 itens carimbados).

Novidades desta rodada:
- `SkillRegistry` passa a ler o catálogo Markdown com precedência (embutidas → repositório → projeto); skill inválida é isolada, nunca derruba a execução.
- `SkillSelector` casa palavra inteira (evita `api` dentro de `rapido`), aplica critérios de não-ativação e aceita a estratégia como entrada (`select_for_strategy`).
- `ProfessionalStrategist` ganhou o domínio `quality_assurance` e `needs_atomization`; `from_dict()` reidrata a estratégia dos metadados.
- `adaptive_decompose_operation()` escolhe a trilha pelo domínio e respeita `max_depth`; `depth_guard()` protege contra repetição de título.
- Ciclo de recuperação da verificação: diagnóstico por causa → ação automática ou manual → re-verificação com orientação no prompt.
- Configurações novas: `skills_max_per_operation` (2) e `verification_max_recoveries` (2).