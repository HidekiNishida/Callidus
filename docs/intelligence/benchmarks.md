# Benchmarks

Engine de benchmarking do Callidus: laboratório de testes para comparar modelos, arquiteturas e configurações.

## Tipos de benchmark

O engine suporta execução de cenários versionados com diferentes modelos e configurações. As quatro categorias descritas na especificação (Model, Architecture, End-to-End, Stress) são implementadas através de diferentes combinações de cenário, provedor e configuração.

## Cenários

Cada cenário contém:

| Campo | Descrição |
|-------|-----------|
| `id` | Identificador estável |
| `version` | Versão do cenário |
| `name` | Nome legível |
| `description` | O que o cenário avalia |
| `category` | Categoria de avaliação |
| `difficulty` | Nível de dificuldade (fácil/intermediário/difícil) |
| `prompt` | Objetivo enviado ao agente |
| `context_initial` | Contexto inicial opcional |
| `tools_allowed` | Ferramentas permitidas |
| `token_budget` | Orçamento de tokens |
| `time_limit_sec` | Limite de tempo |
| `acceptance_criteria` | Critérios de aceite verificáveis |
| `validation_tests` | Testes de validação automatizados |

Categorias iniciais: compreensão de solicitações, planejamento, decomposição, operações estruturadas, uso de ferramentas, leitura de arquivos, escrita e edição, depuração, testes, recuperação de falhas, gestão de contexto, compactação, retomada de execução, tarefas multi-etapas, conclusão end-to-end.

## Pontuação

Cada dimensão recebe pontuação de 0 a 100 com critérios explícitos:

| Dimensão | Critério |
|----------|----------|
| compreensão | Tarefa concluída com evidência verificável |
| planejamento | Menos de 3 recuperações indica planejamento adequado |
| decomposição | Proporção de subtarefas concluídas |
| execução | Taxa de sucesso de chamadas ao modelo |
| uso_ferramentas | Chamadas de ferramenta por tarefa concluída (ideal: 5-10) |
| contexto | Poucas compactações e pouca pressão de orçamento |
| recuperação | Recuperações executadas com sucesso |
| verificação | Taxa de sucesso de verificações independentes |
| conclusão | Taxa de conclusão de tarefas |
| eficiência | Progresso por chamada (produtivas / total) |

## API

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/api/intelligence/benchmarks` | GET | Lista cenários |
| `/api/intelligence/benchmarks` | POST | Cria cenário |
| `/api/intelligence/benchmarks/{id}` | GET | Detalhe do cenário |
| `/api/intelligence/benchmarks/{id}/run` | POST | Executa cenário |
| `/api/intelligence/benchmarks/{id}/results` | GET | Resultados do cenário |
| `/api/intelligence/benchmarks/compare` | GET | Compara execuções |

## Isolamento

Benchmarks rodam em banco isolado. Não modificam projetos reais do usuário, não sobrescrevem arquivos e não compartilham estado entre execuções.

## Exemplos

```python
from agent.intelligence.benchmarks import BenchmarkEngine, BenchmarkScenario

engine = BenchmarkEngine(session)

# Criar cenário
scenario = BenchmarkScenario(
    id="bench-planning-01",
    version=1,
    name="Planejamento de tarefa",
    description="Avalia capacidade de decomposição",
    category="planejamento",
    difficulty="intermediário",
    prompt="Crie um sistema de login com validação",
)
engine.create_scenario(scenario)

# Executar
import asyncio
result = asyncio.run(engine.run_scenario(
    scenario_id="bench-planning-01",
    provider="ollama",
    model_id="llama3.2",
))
print(f"Pontuação: {result.scores}")
print(f"Concluída: {result.task_completed}")
```

## Comparação

O endpoint `compare` permite comparar múltiplas execuções de um mesmo cenário lado a lado, apresentando métricas e pontuações para cada uma.
