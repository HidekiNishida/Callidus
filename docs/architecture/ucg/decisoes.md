# Decisões do Unified Cognitive Graph (UCG)

Decisões arquiteturais tomadas para implementar o UCG sobre o Callidus existente.

## Sumário

1. [Modelo de nó e referência](#modelodenóereferência)
2. [Vocabulário de relacionamentos](#vocabulárioderelacionamentos)
3. [Proveniência](#proveniência)
4. [Tempo e validade](#tempoevalidade)
5. [Isolamento de escopo](#isolamentodeescopo)
6. [Integração sobre tabelas existentes](#integraçãosobretabelasexistentes)
7. [Restrições de grafo](#restriçõesdegrafo)
8. [Decisões adiadas ou rejeitadas](#decisõesadiadasourejeitadas)

## Modelo de nó e referência

Todo nó do UCG possui identidade e tipo definidos. Não se cria uma tabela universal paralela às existentes.

**Decisão:** o nó do UCG é uma referência tipada às entidades já persistidas (`kg_nodes`, `memory_records`, `tasks`, `evidence`, `task_contracts`, `inference_records`). O registro central de nós é a projeção de leitura sobre `KgNodeModel` para o grafo do projeto e sobre as demais tabelas para os demais domínios.

```python
GraphNodeRef:
    id              # identificador estável da linha de origem
    domain          # knowledge | memory | capability | research | task | agent | decision | execution | quality | strategy
    kind            # KNOWLEDGE | CONCEPT | FILE | SYMBOL | DOCUMENT | MEMORY | SKILL | MCP | TOOL | AGENT | MODEL | PROVIDER | RESEARCH_SOURCE | RESEARCH_FINDING | TASK | EXECUTION | DECISION | HYPOTHESIS | STRATEGY | REQUIREMENT | TEST | EVIDENCE
    source_system   # kg | memory | task | evidence | capability | agent | decision | execution | quality | strategy
    source_id       # identificador na tabela de origem
    project_id      # escopo de isolamento
    scope           # global | projeto | conversa | tarefa | execucao | agente
    version         # versão do registro de origem
    status          # ativo | expirado | substituido | bloqueado
    metadata        # JSON com proveniência, confiança, validade
```

Justificativa técnica: duplicar todos os fatos em uma tabela `ucg_nodes` universal exigiria política de sincronização em tempo real contra 14 modelos existentes, violando o princípio de não manter dois registros independentes do mesmo fato. A referência tipada mantém a fonte de verdade em cada domínio e o UCG atua como camada de integração e consulta.

Os tipos de nó são registrados de forma controlada (enum + registro de expansão), sem espalhar condicionais por todo o sistema.

## Vocabulário de relacionamentos

**Decisão:** relações centralizadas com tipo, origem permitida, destino permitido, direção, cardinalidade, significado, regras de validade, participação em expansão recursiva e participação em dependências obrigatórias.

Relações mínimas implementadas:

| Relação | Origem | Destino | Direção | Expansão | Dependência obrigatória |
|---------|--------|---------|---------|----------|-------------------------|
| RELATED_TO | qualquer | qualquer | não direcionada | sim | não |
| DEPENDS_ON | TASK | TASK | direcionada | não | sim |
| REQUIRES | TASK | CAPABILITY/TOOL/MCP | direcionada | sim | sim |
| SUPPORTS | CAPABILITY | TASK | direcionada | sim | não |
| IMPLEMENTS | CAPABILITY | REQUIREMENT | direcionada | sim | não |
| DOCUMENTS | DOCUMENT | FILE/SYMBOL | direcionada | sim | não |
| CONSUMES | TASK | TOOL | direcionada | sim | sim |
| PRODUCES | TASK | ARTIFACT/EVIDENCE | direcionada | sim | não |
| EXECUTED_BY | TASK | AGENT | direcionada | sim | sim |
| VALIDATES | TEST/VERIFICATION | TASK/REQUIREMENT | direcionada | sim | não |
| EVIDENCED_BY | DECISION/HYPOTHESIS | EVIDENCE | direcionada | sim | não |
| DERIVED_FROM | qualquer | qualquer | direcionada | sim | não |
| CONTRADICTS | DECISION/HYPOTHESIS | DECISION/HYPOTHESIS | não direcionada | não | não |
| SUPERSEDES | MEMORY/KNOWLEDGE | MEMORY/KNOWLEDGE | direcionada | não | não |
| SIMILAR_TO | qualquer | qualquer | não direcionada | sim | não |
| DISCOVERED_BY | RESEARCH_FINDING | RESEARCH_SOURCE | direcionada | sim | não |
| USED_IN | CAPABILITY | TASK | direcionada | sim | não |
| APPLICABLE_TO | CAPABILITY | TASK/REQUIREMENT | direcionada | sim | não |
| BLOCKED_BY | TASK | TASK | direcionada | não | sim |

Não é permitido criar uma relação inválida (origem/destino não compatíveis) simplesmente porque os dois nós existem. A validação ocorre no `GraphRepository.validate_relationship`.

## Proveniência

**Decisão:** todo dado relevante no UCG permite descobrir de onde veio, quando foi obtido, qual processo o criou, qual versão/execução o produziu, se foi validado, qual sua confiança, quando foi atualizado e qual sua validade conhecida.

Os campos de proveniência são carregados nos `metadata_json` das tabelas de origem (ex.: `meta_json` de `KgNodeModel`, `source_refs_json` de `MemoryRecordModel`, `metadata_json` de `TaskModel`). O UCG não cria colunas novas; expõe a proveniência via `GraphNodeRef.metadata`.

Informação sem origem identificável não é tratada como conhecimento confiável.

## Tempo e validade

**Decisão:** diferencia-se conhecimento permanente, conhecimento temporal, estado atual, resultado histórico, informação expirada e informação substituída.

- Nós de conhecimento técnico (arquivo, símbolo, documento) têm validade vinculada ao hash do arquivo (`inspection.py` detecta stale) e à versão do projeto.
- Memórias têm `created_at` e `version` (`MemoryRecordModel`); a camada de arquivo histórico (`layers.py`) armazena registros extensos recuperados sob demanda.
- Capacidades (skill, MCP, ferramenta) têm disponibilidade com TTL; não se confia indefinidamente em disponibilidade previamente registrada.
- Relações `SUPERSEDES` marcam substituição de versões antigas sem apagá-las silenciosamente.

## Isolamento de escopo

**Decisão:** nenhuma consulta mistura dados de projetos, conversas ou escopos sem autorização.

Escopos definidos: global, usuário, projeto, conversa, tarefa, execução, agente. A consulta ao UCG aceita `project_id` obrigatório e, opcionalmente, `conversation_id`, `task_id`, `run_id` e `agent_id`. O `project_id` tem precedência; herança de visibilidade é do escopo mais restrito para o mais amplo, nunca o inverso.

## Integração sobre tabelas existentes

**Decisão:** nenhuma nova tabela é criada para o núcleo do UCG. As tabelas reaproveitadas são:

- `kg_nodes` / `kg_edges` — Knowledge Graph do projeto (nós: arquivo, símbolo, documento, módulo, requirement; arestas: contains, defines, imports, tests, documents, related_to).
- `memory_records` — Memory Graph (kinds: operational, task_detail, artifact, canonical, contextual, evidence, procedure, execution).
- `tasks` / `task_contracts` / `task_dependency` — Task Graph e Execution Graph.
- `evidence` — Decision Graph e Quality Graph (veredito, sumário, detalhe).
- `inference_records` — Strategy Graph (tokens, custo, duração, sucesso).

Quando for estritamente necessário materializar uma projeção derivada (ex.: cache de relevância de inspeção), o dado é gravado em `metadata_json` da tarefa ou em cache em memória existente, nunca em tabela nova.

## Restrições de grafo

**Decisão:** não se aplica uma regra de travessia única a todos os domínios.

- Grafos de conhecimento e memória podem conter ciclos (ex.: conceito A relacionado a conceito B e B relacionado a A).
- Dependências de execução (Task Graph) devem ser acíclicas; ciclos são detectados e bloqueados antes do planejamento.
- Relações de evidência preservam proveniência (não são agregadas anonimamente).
- Capacidades têm aplicabilidade e permissões (recurso conhecido ≠ recurso autorizado ≠ recurso executável).

Detecção de ciclo: implementada no `GraphQueryEngine.traverse` com `visited` e limite de profundidade; dependências obrigatórias (`DEPENDS_ON`, `REQUIRES`, `CONSUMES`, `EXECUTED_BY`, `BLOCKED_BY`) são validadas quanto a aciclicidade quando usadas para planejamento.

## Decisões adiadas ou rejeitadas

| Decisão | Status | Motivo |
|---------|--------|--------|
| Tabela universal `ucg_nodes` duplicando todos os fatos | rejeitada | viola o princípio de não duplicar registros sem política de sincronização |
| Neo4j / banco de grafos externo | rejeitada | não há benchmark que justifique; SQLite + índices relacionais são suficientes |
| Busca vetorial obrigatória | adiada | estratégia opcional, somente se utilidade e custo forem comprovados |
| Cache distribuído (Redis) | rejeitada | cache em memória ou persistente existente é suficiente para máquinas modestas |

## Verificação

```bash
source .venv/bin/activate && python scripts/ci.py --rapido
```

## Links cruzados

- [auditoria do UCG](auditoria.md)
- [roadmap do UCG](roadmap.md)
- [Visão geral da arquitetura](../visao-geral.md)
- [Contratos que não podem quebrar (AGENTS.md §9)](../../../AGENTS.md)
