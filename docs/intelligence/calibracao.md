# Calibração adaptativa — Inteligência e Observabilidade

Calibração adaptativa do Callidus: ajuste automático de parâmetros operacionais com base
em evidências de execução real, mecanismo campeão/desafiador com rollback e histórico
persistido. Não altera pesos de modelos, nem código-fonte, nem regras de segurança por
inferência comum.

## Por que existe

O Callidus roda em máquinas modestas (cerca de 16 GB de RAM, 6–8 GB de VRAM) com um único
modelo local (`my_ollama` / `gpt-oss:20b` por configuração). Parâmetros fixos (janela de
contexto, reserva de saída, granularidade de decomposição, tentativas, inspeções) não servem
para todos os tipos de trabalho: uma consulta simples não precisa de decomposição hierárquica,
e um subsistema complexo não pode ser tratado como uma única operação.

A calibração permite descobrir, por perfil de trabalho, quais parâmetros produzem melhor
taxa de conclusão com menos tokens e inferências, e promover apenas configurações que
melhorem de fato — com reversão quando houver regressão.

## Componentes

| Componente | Arquivo | Responsabilidade |
|------------|---------|------------------|
| `OperationalProfile` / `ProfileCatalog` | `src/agent/learning/profiles.py` | Perfis nomeados por tipo de trabalho com limites configuráveis |
| `CapabilityDiscovery` / `discover_capabilities` | `src/agent/learning/capability_discovery.py` | Descoberta de capacidades do provedor e do ambiente |
| `CalibrationEngine` / `CalibrationStore` | `src/agent/learning/calibration.py` | Campeão/desafiador, avaliação, rollback, histórico |

## Perfis operacionais

Cada perfil define limites para um tipo de trabalho (`consulta`, `investigacao`,
`planejamento`, `implementacao`, `correcao`, `refatoracao`, `testes`, `documentacao`,
`verificacao`, `pesquisa`, `automacao`):

- `context_budget`: orçamento de tokens de entrada para o modelo.
- `output_reserve`: reserva de tokens de saída que a implementação não pode gastar.
- `decomposition_granularity`: `simple`, `hierarchical` ou `recursive`.
- `max_recursion_depth`: profundidade máxima de delegação recursiva.
- `max_attempts`: tentativas máximas por problema.
- `max_inspections`: leituras máximas de inspeção.
- `max_tool_iterations` / `max_tool_calls`: orçamento do ciclo de ferramentas.
- `verification_intensity`: `low`, `medium` ou `high`.
- `skills_selected`: skills selecionadas (`None` = todas).
- `max_model_calls`: chamadas ao modelo permitidas.
- `timeout_sec`: tempo limite da operação.

Os valores são defaults seguros e **nunca ultrapassam os limites globais** de
`agent.config.Settings` (ex.: `default_context_limit`, `max_attempts_per_task`).
Quando um valor de perfil excede o global, o global vence.

Perfis podem ser registrados, sobrepostos (calibração adaptativa) e redefinidos
(rollback) via `ProfileCatalog`.

## Descoberta de capacidades

`discover_capabilities(settings)` identifica, sempre que verificável:

- provedor conectado, modelo, URL base e tipo;
- sistema operacional, CPUs, RAM;
- limite real de contexto do modelo (via `/api/tags` do Ollama, `details.context_length`);
- suporte a streaming, ferramentas, saída estruturada e visão (do contrato do provedor);
- limite de inferências simultâneas (`max_concurrent_inferences`).

Campos que não podem ser verificados (ex.: GPU/VRAM sem suporte do fornecedor, servidor
indisponível) são reportados como `null` ou `"desconhecido"` — nunca presumidos a partir
da configuração declarada. Nunca se confia cegamente no modelo declarado pelo provedor.

## Calibração adaptativa (campeão/desafiador)

O campeão é a configuração corrente confiável (perfil ativo no `ProfileCatalog`).
O desafiador é uma mudança candidata registrada com:

- identificador, tipo de trabalho, parâmetro, valor anterior e valor novo;
- origem (`manual`, `experimento`, `diagnostico`), justificativa e hipótese;
- versão e cenário de avaliação.

### Fluxo

1. **Execuções reais** geram telemetria e métricas (tokens, chamadas, duração, taxa de
   sucesso, falsos completos, recuperações).
2. **Diagnóstico de desempenho** identifica o gargalo e formula uma hipótese de melhoria.
3. **Experimento controlado** registra a mudança candidata (`register_change`).
4. **Benchmark comparativo** mede campeão vs desafiador em cenários comparáveis (`evaluate`).
5. **Avaliação da qualidade:** o desafiador é promovido somente quando há melhoria real
   (ex.: ≥ 5 % relativa) **sem regressão** (taxa de sucesso não cai, falsos completos não
   aumentam) e com amostras suficientes (≥ 3 execuções).
6. **Nova calibração:** se promovido, o desafiador vira o campeão; caso contrário, mantém-se
   o campeão ou reverte.
7. **Perfil versionado:** cada promoção grava um perfil versionado para próximas execuções.

### Decisões

| Decisão | Significado |
|---------|-------------|
| `promote` | Desafiador vira o novo campeão (melhorou sem regressão). |
| `revert` | Desafiador causou regressão; volta ao campeão. |
| `keep` | Dados insuficientes ou sem diferença relevante; mantém o campeão. |
| `blocked` | Mudança insegura (ex.: parâmetro crítico alterado manualmente); bloqueada. |

Parâmetros críticos de segurança (ex.: `max_attempts`, `max_tool_calls`,
`max_tool_iterations`) alterados manualmente são sempre bloqueados — exigem origem
`diagnostico` com revisão explícita.

## Histórico e rollback

Toda mudança e decisão é persistida (`data/calibration.db`, banco aditivo, sem mexer no
`data/agent.db` do usuário) com valores anterior/novo, origem, versão, justificativa,
confiança, melhoria relativa, regressão e carimbo de data/hora.

O rollback desativa uma mudança e volta ao último perfil confiável. A calibração nunca
remove proteções fundamentais de segurança para aumentar velocidade.

## Limites de segurança

- Uma inferência de modelo local por vez (`max_concurrent_inferences = 1`).
- Nenhum benchmark pesado é executado automaticamente a cada inicialização; apenas
  verificações leves de saúde no início.
- Calibrações mais completas ocorrem sob demanda ou em períodos ociosos.
- Aprendizado operacional é rastreável, reversível e baseado em evidências — nunca altera
  código-fonte, regras de segurança ou limites globais por inferência comum.

## API

Os endpoints estão em `src/agent/api/intelligence_routes.py`:

| Endpoint | Descrição |
|----------|-----------|
| `GET /api/intelligence/capabilities` | Capacidades observadas do provedor e ambiente |
| `GET /api/intelligence/profiles` | Perfis operacionais e limites aplicados |
| `GET /api/intelligence/calibration/history` | Histórico de mudanças e decisões |
| `POST /api/intelligence/calibration/change` | Registra uma mudança candidata |
| `POST /api/intelligence/calibration/evaluate` | Avalia campeão vs desafiador |
| `POST /api/intelligence/calibration/rollback/{id}` | Desativa uma mudança (rollback) |
| `GET /api/intelligence/dashboard` | Painel consolidado de desempenho |

## Exemplos

```python
from agent.learning.profiles import create_profile_catalog
from agent.learning.capability_discovery import discover_capabilities
from agent.config import Settings

settings = Settings()
catalog = create_profile_catalog(settings)
perfil = catalog.profile_for("implementacao")
print(perfil.limit.context_budget, perfil.limit.output_reserve)

cap = discover_capabilities(settings)
print(cap.context_limit, cap.measurement_quality)
```

```python
from agent.learning.calibration import (
    create_calibration_store, create_calibration_engine, CalibrationMetrics,
)

store = create_calibration_store("data/calibration.db")
engine = create_calibration_engine(store)

change = engine.register_change(
    work_type="implementacao",
    parameter="context_budget",
    previous_value=8192,
    new_value=12000,
    origin="experimento",
    justification="mais contexto para arquivos grandes",
    hypothesis="reduz replanejamentos sem perder qualidade",
)

campeao = CalibrationMetrics(success_rate=0.90, tokens_per_task=1000, calls_per_task=10,
                             duration_ms=5000, false_completion_rate=0.05, recovery_count=0)
desafiador = CalibrationMetrics(success_rate=0.90, tokens_per_task=800, calls_per_task=9,
                                duration_ms=4000, false_completion_rate=0.04, recovery_count=0)
decisao = engine.evaluate(change.id, campeao, desafiador, samples=5)
print(decisao.decision, decisao.confidence, decisao.improvement)
```

## Relacionado

- [architecture.md](./architecture.md) — arquitetura dos subsistemas de inteligência.
- [metrics.md](./metrics.md) — métricas usadas para comparar campeão e desafiador.
- [diagnostics.md](./diagnostics.md) — diagnóstico que alimenta hipóteses de calibração.
- [benchmarks.md](./benchmarks.md) — cenários de comparação antes/depois.
