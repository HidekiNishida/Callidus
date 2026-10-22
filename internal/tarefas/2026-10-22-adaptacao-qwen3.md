# Checklist: adaptação ao qwen3:8b

Auditoria e evolução do Callidus para concluir tarefas com o `qwen3:8b` local pelo Ollama.

| Campo | Valor |
|-------|-------|
| Estado | concluída (medição real com o modelo pendente) |
| Criado em | 2026-10-22 |
| Atualizado em | 2026-10-22 |
| Agente / tarefa | Claude — auditoria qwen3:8b ([G1](/docs/progresso/gaps.md#g1-avaliação-real-ampla-e-repetível), [G11](/docs/progresso/gaps.md#g11-paridade-entre-provedores)) |
| Regras consultadas | [Hub](/docs/regras/README.md), [AGENTS.md](/AGENTS.md), [progresso.md](/docs/regras/progresso.md), [commits.md](/docs/regras/commits.md) |

## 🎯 Objetivo

Encontrar por que tarefas com o `qwen3:8b` não terminam bem e corrigir as causas comprovadas, sem
trocar o modelo de referência (`gpt-oss:20b`) nem os contratos públicos.

## Próxima ação

Rodar `python lab/avaliar.py --label qwen3-depois --model qwen3:8b --provider meu_ollama --max-steps 120`
no Mac (três rodadas) e registrar em [avaliacao.md](/docs/architecture/avaliacao.md).

## 🔄 Etapas

- [x] Criar este arquivo a partir do modelo e preencher metadados
- [x] Linha de base: 908 aprovados, 1 reprovado (`test_end_to_end_requirements`, já em `d180d09`), 1 pulado
- [x] Evidência do banco do usuário (cópia, só leitura): estimativa de tokens 12–56 % abaixo do real; plano de 7 626 tokens em 466 s
- [x] Causa do teste reprovado: estado de tarefas irmãs nas regras do projeto → corrigido em `context/operation_builder.py`
- [x] Ollama sem `num_ctx` (padrão do servidor, 4 096 abaixo de 24 GiB) e sem `num_predict` → `providers/ollama_policy.py`
- [x] Estimativa de tokens calibrada (3 caracteres por token) → `providers/base.py`
- [x] Conversa do ciclo de ferramentas dentro da janela → `orchestrator/tool_loop.fit_history`
- [x] `<think>` e `<tool_call>` escritos no texto → `ollama.normalize_reply`
- [x] Plano inválido: uma recuperação com esquema imposto → `decomposition._repair_plan`
- [x] Amostragem do qwen3 por finalidade (`ChatCompletionRequest.purpose`)
- [x] Testes: `tests/test_qwen3_ollama_policy.py`, `tests/test_qwen3_context.py`, `tests/test_qwen3_plan_repair.py`
- [x] Comparação antes/depois com servidor simulado (`scripts/simular-qwen3.py`)
- [x] Documentação: provedores, orçamento de contexto, ciclo de ferramentas, avaliação, `resume.md`, progresso
- [x] Verificação: suíte Python (929 aprovados, 1 pulado), interface (57), cabeçalhos, links, referências, Markdown, `resume.md`
- [ ] Medição com o `qwen3:8b` real (o Ollama não estava acessível no ambiente da auditoria)

## Bloqueios

- O Ollama do Mac não é acessível do ambiente da auditoria: nenhuma inferência real foi feita.
- O `ruff` do projeto (0.17) não estava disponível; o lint foi feito com o `ruff` 0.14 — nenhum achado novo em relação a `d180d09` (os 58 achados existentes continuam).

## Artefatos

| Path absoluto | Notas |
|---------------|-------|
| `/src/agent/providers/ollama_policy.py` | política por família do Ollama |
| `/scripts/simular-qwen3.py` | medição antes/depois sem modelo real |
| `/docs/architecture/avaliacao.md` | resultado da simulação e a medição real pendente |

## Notas de retomada

A política só preenche o que `generation` não traz: para testar outra amostragem ou janela, ponha a
chave em `generation` do provedor em `data/providers.yaml`. O `gpt-oss` e o `deepseek-r1` ficaram
fora da política de propósito (modelo de referência). Os metadados de cada inferência ficam em
`inference_records.provider_meta_json.adapter`.
