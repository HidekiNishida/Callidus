# Ações das automações

O que a automação **faz** quando dispara: a ação é um contrato executável, registrado por
tipo e escolhido pelo `executor.py` no momento do disparo.

| Arquivo | Responsabilidade |
|---------|------------------|
| [`base.py`](base.py) | Contrato `Action` e o registro de tipos (`register_action`, `action_factories`, `build_action`) |
| [`callidus.py`](callidus.py) | Ação **Callidus**: cria a tarefa raiz e entrega o trabalho ao worker autônomo |
| [`script.py`](script.py) | Ação **de script**: executa um comando determinístico, sem depender de inferência |

## 🛠️ Como criar uma ação nova

1. Implemente o contrato `Action` (método `execute(ctx) -> ActionResult`).
2. Registre com `register_action(kind, factory)` no `__init__.py` da pasta.
3. Declare o tipo em `agent/automation/enums.py` e o contrato em `contracts.py`.

A ação é executada pelo `executor.py`, que já cuida de dependências, permissões, registro do
disparo e evidência — a ação entrega apenas o resultado da sua execução.

**Voltar:** [automation/README.md](../README.md) · **Voltar:** [src/agent/README.md](../../README.md) · [Raiz](/README.md)