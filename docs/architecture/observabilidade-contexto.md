# Observabilidade de Contexto e Tokens por Inferência

## Propósito

Ampliar a funcionalidade de Inteligência do Callidus para medir, classificar, visualizar, comparar e otimizar o consumo de contexto e tokens de cada inferência individual. A funcionalidade está integrada na área **Inteligência** (página **Consumo e Gestão de Contexto**) e na **conversa do agente** (barra de observabilidade por inferência na linha do tempo).

## Modelo de dados

Não foram criadas novas tabelas. A estrutura existente em `src/agent/persistence/models.py` foi reutilizada e estendida:

- `InferenceRecordModel` (`inference_records`): já existia com `prompt_tokens`, `completion_tokens`, `reasoning_tokens`, `cache_read_tokens`, `cache_write_tokens`, `estimated_prompt_tokens`, `estimated_completion_tokens`, `context_snapshot_id`, `provider_meta_json`, `components_included_json`, `tool_results_attached_json`, `external_refs_json`, `compaction_events_json`, `budget_pressure`, `input_budget_used`, `output_reserve_used`, `calibration_ratio`. Foram acrescentadas as colunas:
  - `parent_task_id` (CHAR(32), FK para `tasks.id`): tarefa pai, quando a inferência pertence a um agente filho.
  - `inference_type` (VARCHAR(32)): tipo da inferência da taxonomia.
  - `context_window_size` (INTEGER): tamanho da janela de contexto do modelo.
  - `tokenizer_version` (VARCHAR(64)): versão da estratégia de contagem.
  - `tokenizer_strategy` (VARCHAR(64)): estratégia usada (ex.: `chars_per_token:3`).
- `ContextSnapshotModel` (`context_snapshots`): já existia com `components_json` e `categories_json`. Os componentes gravados no snapshot alimentam `components_included_json` da inferência via `_enrich_components` em `ledger.py`.
- Índices adicionados: `ix_inference_parent_task` e `ix_inference_type`.

A migração SQLite (`_migrate_sqlite` em `database.py`) adiciona as colunas de forma idempotente, sem destruir dados.

## Classificação de tipo de inferência

A taxonomia é atribuída pelo orquestrador conforme a operação em execução (nunca pelo texto gerado pelo modelo), em `src/agent/domain/enums.py` (`InferenceType`):

| Tipo | Significado |
|------|-------------|
| `planning` | Planejamento da tarefa |
| `task_decomposition` | Decomposição em subtarefas |
| `execution` | Execução de operação / modelo |
| `tool_selection` | Seleção de ferramenta |
| `tool_result_analysis` | Análise de resultado de ferramenta |
| `verification` | Verificação de resultado |
| `error_correção` | Correção de erro |
| `recovery` | Recuperação após falha |
| `research` | Pesquisa de conhecimento |
| `memory_retrieval` | Recuperação de memória |
| `context_summarization` | Resumo / compactação de contexto |
| `final_response` | Resposta final ao usuário |
| `diagnostic` | Diagnóstico |
| `calibration` | Calibração / experimentação |
| `other` | Outro / não identificado |

O mapeamento da `purpose` da requisição para o tipo fica em `classify_inference_type` (`src/agent/orchestrator/inference_usage.py`).

## Classificação de componentes do contexto

Segunda classificação independente, em `ContextComponentCategory` (`src/agent/domain/enums.py`), que identifica os componentes que formam o prompt: `system_instructions`, `agent_instructions`, `task_instructions`, `conversation_history`, `parent_agent_context`, `child_agent_context`, `short_term_memory`, `long_term_memory`, `knowledge_retrieval`, `tool_definitions`, `tool_calls`, `tool_results`, `files_and_documents`, `code_context`, `research_results`, `compaction_summaries`, `output_format_and_schemas`, `provider_metadata`, `other`.

Cada componente pode registrar: categoria, identificação, descrição, quantidade de tokens, origem, agente responsável, tarefa relacionada, se é conteúdo novo ou reutilizado, se foi resumido/truncado/compactado, estratégia de inclusão, possibilidade de otimização e confiança da medição. Componentes podem ter subcomponentes (ex.: `tool_results` subdividido por ferramenta).

## Precisão e integridade das métricas

São distinguidos obrigatoriamente:

1. Tokens estimados por componente antes do envio (`estimated_prompt_tokens`, `estimated_completion_tokens`).
2. Tokens de entrada informados pelo provedor (`prompt_tokens`).
3. Tokens de saída informados pelo provedor (`completion_tokens`).
4. Tokens em cache (`cache_read_tokens`, `cache_write_tokens`).
5. Tokens de raciocínio (`reasoning_tokens`).
6. Tamanho estimado/informado do contexto utilizado (`context_window_size`).
7. Limite total da janela de contexto do modelo.

Regras:
- Estimativa nunca é tratada como valor real; ausência permanece `None`, nunca zero.
- Cada token pertence a uma única parcela do orçamento contabilizado, ou é explicitamente marcado como sobreposição não aditiva.
- Tokenizador compatível com o modelo quando disponível; caso contrário, a heurística local (`chars_per_token:3`, calibrada contra Ollama) é usada e declarada.
- Versão e estratégia do tokenizador são registradas em cada inferência (`tokenizer_version`, `tokenizer_strategy`).

## Instrumentação

Toda chamada ao modelo passa por `observed_chat` (`src/agent/providers/observed.py`), que grava um `InferenceRecord` idempotente via `record_inference` (`src/agent/orchestrator/ledger.py`). A gravação:
- Classifica o tipo de inferência a partir da `purpose`.
- Captura o tamanho da janela do perfil do modelo.
- Registra versão e estratégia do tokenizador.
- Enriquece `components_included_json` a partir do `ContextSnapshotModel` vinculado.
- Falhas de telemetria nunca bloqueiam a execução (try/except absorve exceções).

## Endpoints

Todos sob `/api/intelligence/` (`src/agent/api/intelligence_routes.py`):

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/context-consumption/overview` | GET | Visão geral: totais de entrada/saída, média por inferência, janela média, compactação, tokens economizados. |
| `/context-consumption/by-type` | GET | Estatísticas (média, mediana, p90, p95, min, max) por tipo de inferência. |
| `/context-consumption/by-component` | GET | Tokens acumulados por categoria, percentual, ocorrências, potencial de otimização. |
| `/context-consumption/matrix` | GET | Matriz que cruza tipo de inferência com componente do contexto. |
| `/context-consumption/compare` | GET | Compara consumo por modelo, agente, provedor, tarefa ou tipo (`group_by`). |
| `/context-consumption/timeline` | GET | Evolução temporal do consumo por período (dia/semana/mês). |
| `/context-consumption/opportunities` | GET | Oportunidades de otimização com evidência, frequência, impacto e estratégia. |
| `/inferences/{inference_id}` | GET | Detalhe de uma inferência individual. |
| `/inferences/{inference_id}/components` | GET | Composição do contexto de uma inferência (categorias, tokens, origem). |

Não transfere todo o histórico para o navegador: agregações são feitas no backend e detalhes usam paginação. Os dados sobrevivem a reinicializações (SQLite).

## Estatísticas

Disponíveis: média aritmética, mediana (p50), percentis p90, p95, p99 (quando houver amostra suficiente), mínimo, máximo, desvio padrão quando útil e quantidade de amostras. Agrupamentos por tipo de inferência, componente do contexto, agente, modelo, provider, tarefa, projeto, período e resultado da execução. Separadas inferências concluídas, falhas, canceladas e tentativas de recuperação.

## Análise e oportunidades de otimização

O serviço identifica padrões (em `opportunities`):

- Histórico crescendo excessivamente.
- Instruções duplicadas.
- Definições de ferramentas muito grandes.
- Resultados de ferramentas desnecessariamente extensos.
- Arquivos enviados integralmente quando trechos bastariam.
- Memórias recuperadas sem relação com a tarefa.
- Resumos que continuam grandes.
- Contexto repetido entre inferências.
- Agentes filhos recebendo informações desnecessárias.
- Inferências que consomem muitos tokens sem produzir progresso verificável.

Para cada oportunidade: problema, evidência e amostra, componente responsável, frequência, impacto estimado, estratégia recomendada, risco de perda de informação e resultado esperado. Nenhuma mudança automática é executada somente porque uma categoria consome muitos tokens.

## Experimentação e calibração

A integração com o mecanismo de calibração existente (`/api/intelligence/calibration/*`) permite testar estratégias alternativas (redução do histórico, seleção de mensagens relevantes, recuperação seletiva de memória, compactação de resultados de ferramentas, extração de trechos, redução de instruções redundantes, alteração do contexto transferido a agentes filhos). Uma otimização só é bem-sucedida se reduzir o consumo sem prejudicar a qualidade ou a taxa de conclusão.

## Regras de arquitetura preservadas

- Funcionamento atual do orquestrador preservado.
- Não duplica o ledger de tokens.
- Instrumentação conectada às chamadas reais do modelo.
- Sem concorrência adicional no mecanismo de inferência.
- Falha de telemetria não trava a execução.
- Componentes reutilizáveis no Vue.
- Responsabilidades separadas entre coleta, persistência, agregação, análise e apresentação.
- Compatível com Ollama, llama.cpp e provedores OpenAI-compatível.
- Campos indisponíveis não quebram a interface.

## Testes

Suíte em `tests/test_context_consumption.py` (41 testes):

- `classify_inference_type`: mapeamento de finalidades conhecidas e desconhecidas, ausência de finalidade.
- `overview`: totais, média, janela, compactação, tokens economizados.
- `by_inference_type`: agrupamento e estatísticas por tipo.
- `by_component`: agregação por categoria, percentual, potencial de otimização.
- `matrix`: cruzamento tipo × componente.
- `compare`: agregação por dimensão (modelo, agente, provedor…).
- `timeline`: evolução por período.
- `opportunities`: identificação de padrões de consumo excessivo.
- `get_inference` / `get_inference_components`: detalhe de inferência individual e componentes; ausência retorna `None`.

Suíte completa: 1367 testes passando, sem regressões. Lint (ruff) limpo.

## Limitações

- Tokens de cache e raciocínio não entram novamente no total de entrada ou saída.
- Estimativas locais usam heurística de caracteres por token quando o provedor não informa contagem exata.
- A janela de contexto é a configurada no perfil do run; provedores sem política explícita usam o padrão do processo.
- Nenhuma mudança automática é executada com base apenas no consumo de categoria.
- O `resume.md` ainda não está totalmente carimbado devido a itens pré-existentes não descritos (componentes `intelligence-*.js` e `closing.py` anteriores a esta funcionalidade).
