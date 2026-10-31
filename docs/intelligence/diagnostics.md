# Diagnósticos

Motor de diagnóstico determinístico do Callidus. Identifica gargalos, desperdícios, falhas e oportunidades de otimização a partir de evidências persistentes.

## Princípios

- **Separação clara:** problema comprovado ≠ anomalia estatística ≠ hipótese ≠ recomendação.
- **Não afirmar causalidade sem evidência direta:** correlação não é causa.
- **Determinístico:** primeiro versão não depende de modelo de linguagem.
- **Evidência sempre anexada:** cada diagnóstico cita as observações que o fundamentam.

## Categorias

| Categoria | Descrição |
|-----------|-----------|
| `gargalo_inferencia` | Muitas chamadas com alta latência ou erro |
| `excesso_retries` | Mesma falha repetida em múltiplas tentativas |
| `excesso_compactacao` | Contexto excede orçamento, exige múltiplas compactações |
| `contexto_redundante` | Uso de estimativas sem contagem reportada |
| `falha_recorrente` | Mesma falha em diferentes tarefas |
| `ferramenta_lenta` | Ferramentas com tempo de execução elevado |
| `verificacao_repetida` | Muitas tentativas de verificação |
| `etapa_custa_demais` | Baixa taxa de conclusão com muitas chamadas |
| `queda_qualidade` | Queda de qualidade entre versões |
| `contexto_excedido` | Janela de contexto ultrapassada |

## Severidades

| Severidade | Significado |
|------------|-------------|
| `baixa` | Ajuste opcional, impacto mínimo |
| `media` | Deve ser corrigido no próximo ciclo |
| `alta` | Impacto na conclusão, corrigir antes do próximo release |
| `critica` | Bloqueia execução, ação imediata |

## Tipos de diagnóstico

| Tipo | Significado |
|------|-------------|
| `problema_comprovado` | Evidência direta do problema |
| `anomalia_estatistica` | Desvio estatístico sem causalidade comprovada |
| `hipotese` | Explicação plausível não confirmada |
| `recomendacao` | Ação sugerida com base em evidências |

## API

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/api/intelligence/diagnostics` | GET | Lista diagnósticos (filtros: run_id, category, severity, state) |
| `/api/intelligence/diagnostics/{id}` | GET | Detalhe de um diagnóstico |
| `/api/intelligence/diagnostics` | POST | Cria diagnóstico manualmente |
| `/api/intelligence/diagnostics/runs/{run_id}/analyze` | POST | Executa diagnóstico determinístico sobre uma run |
| `/api/intelligence/diagnostics/summary` | GET | Resumo por categoria, severidade, estado, tipo |

## Detecção automática

O `DiagnosticEngine.analyze_run(run_id)` detecta automaticamente:

1. **Gargalo de inferência:** >10 chamadas com taxa de erro >30%
2. **Excesso de retries:** >5 chamadas com >2 falhas
3. **Excesso de compactação:** >3 eventos de compactação
4. **Contexto redundante:** >20 chamadas com medição apenas estimada
5. **Etapa custa demais:** taxa de conclusão <50% com tarefas na run
6. **Verificação repetida:** >10 tentativas de verificação

Cada diagnóstico inclui: categoria, severidade, evidências, métrica afetada, período observado, causa provável, nível de confiança, recomendação e estado.

## Exemplo

```python
from agent.intelligence.diagnostics import DiagnosticEngine

engine = DiagnosticEngine(session)

# Executar diagnóstico automático
diagnostics = engine.analyze_run(run_id)
for d in diagnostics:
    print(f"{d.category}: {d.probable_cause} -> {d.recommendation}")

# Obter resumo
summary = engine.get_summary()
print(f"Total: {summary['total']}, Críticos: {summary['critical']}, Abertos: {summary['open']}")
```
