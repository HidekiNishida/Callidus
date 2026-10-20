# Ciclo de ferramentas da operação

Módulo: [`src/agent/orchestrator/tool_loop.py`](/src/agent/orchestrator/tool_loop.py) ·
Consumidor: [`runner.py`](/src/agent/orchestrator/runner.py) ·
Provedores: [`ollama.py`](/src/agent/providers/ollama.py), [`openai_compatible.py`](/src/agent/providers/openai_compatible.py)

## O problema

Um modelo treinado para ferramentas (o `gpt-oss:20b` é um deles) **não responde "crie o arquivo
X" com JSON**: ele pede a ferramenta. Enviado um pedido sem ferramentas declaradas, o servidor
devolve `message.content` vazio — o modelo emitiu uma chamada de ferramenta e não havia para onde
emitir. O Callidus tratava isso como "resposta vazia", repetia o mesmo pedido três vezes
(sempre com o mesmo conteúdo, o que não acionava a proteção de prompt repetido) e parava em
estagnação.

Evidência (conversa real de 19/10/2026, run `37ada39b…`): 39 chamadas ao modelo, 21 respostas
vazias, run pausada em `blocked_attempts` sem nenhuma alteração no disco. Reprodução isolada do
pedido com o mesmo modelo: `content` vazio e `thinking` terminando em "Let's read them".

## O que existe agora

A etapa de operação (`metadata.model_operation`) roda um **ciclo de ferramentas** explícito:

1. O modelo recebe as ferramentas da operação como esquemas de função (`tools` na requisição).
2. Se a resposta vier com `tool_calls`, o agente executa cada chamada pelo **registro de
   ferramentas** (mesma validação de caminho, aprovação e diff do resto do agente) e devolve o
   resultado como mensagem `tool`.
3. O modelo continua a partir do resultado até responder.
4. Se o modelo **aplicar** a alteração (`write_file`/`edit_file`), o ciclo termina e a etapa vai
   direto para a verificação.
5. Se o modelo responder em JSON (protocolo antigo), o caminho JSON continua valendo.

```
modelo ──tool_calls──▶ registro de ferramentas ──resultado──▶ modelo
   │                                                             │
   └────────────── resposta em JSON ──▶ verificação ◀──────────┘
```

O prompt da operação (`context/operation_builder.py`) diz ao modelo que ele pode inspecionar com
ferramentas e que a alteração pode ser feita com `write_file`/`edit_file`, e informa o orçamento de
leituras (mesmo limite do ciclo).

## Contratos

| Objeto | Onde | O que garante |
|--------|------|---------------|
| `ToolLoopOutcome` | `tool_loop.py` | `content`, `stop_reason` (`final`, `applied`, `max_iterations`), `reasoning`, `tool_log`, `applied_tool/args/result` |
| `ProviderCapabilities.tool_loop` | `providers/base.py` | Só provedores que sabem manter a conversa de ferramentas entram no ciclo (`ollama`, `openai_compatible`, `llamacpp`) |
| `ChatMessage.tool_calls` / `tool_call_id` | `providers/base.py` | Histórico da conversa de ferramentas |
| `ChatCompletionResponse.reasoning` | `providers/base.py` | Canal de raciocínio (`thinking` do Ollama): sem ele não há como distinguir "modelo pensou e não respondeu" de "resposta inválida" |
| `AttemptKind.MODEL` com `iteration_fp` | `services/attempt_service.py` | Iteração interna do ciclo **não** conta como tentativa da tarefa (o orçamento de tentativas é da estratégia, não das leituras) |

## Limites

- `max_tool_iterations` (padrão 6, `Settings`): rodadas de inspeção. Ao estourar, o ciclo faz uma
  última chamada com o mesmo histórico e a instrução de fazer a alteração agora.
- Repetir a mesma chamada de ferramenta devolve ao modelo o aviso "você já consultou isto".
- A escrita continua passando pelo registro de ferramentas: uma só origem de mutação no disco.
- Provedores sem `tool_loop` (Anthropic, Gemini, mock) seguem no protocolo JSON de uma tacada.

## Diagnóstico

| Sintoma | Causa | O que fazer |
|---------|-------|-------------|
| `resposta vazia: o modelo raciocinou (N caracteres) e não devolveu conteúdo` | o modelo pediu uma ferramenta que não foi oferecida, ou gastou o orçamento pensando | veja `operation_attempts.kind = 'model'`: `response_json.tool_calls` mostra o que ele pediu |
| `resposta vazia: o modelo usou todo o orçamento de N tokens` | corte de saída | `FailureCause.TRUNCATED_OUTPUT` amplia o orçamento na próxima tentativa |
| etapa parada com `mesma chamada de ferramenta falhou de novo` | erro determinístico de entrada repetido | a etapa vai para o replanejamento (outra ferramenta, outro arquivo) |
| `model.tool_call` no log de eventos | o modelo pediu ferramenta durante a operação | evidência do ciclo; o resultado da chamada está em `attempt.recorded` |

Reprodução controlada (mesmo objetivo, mesmo modelo, mesmo ambiente):

```bash
python lab/run_scenario.py <rótulo> <banco.db> <cópia-do-projeto>
```

O script imprime Modelo/Baseline lado a lado: chamadas, respostas vazias, tentativas e estado final.

Testes: [`tests/test_tool_loop.py`](/tests/test_tool_loop.py) (ciclo, esquemas, provider) ·
[`tests/test_model_tool_operation.py`](/tests/test_model_tool_operation.py) (execução completa e
erro repetido).

Voltar: [architecture/README.md](/docs/architecture/README.md)
