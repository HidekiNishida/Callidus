# `src/agent/engineering/` — Descoberta e verificação de projeto

O agente reconhece o projeto e usa as ferramentas que ele já declara.

| Módulo | Papel |
|--------|-------|
| [`discovery.py`](./discovery.py) | Linguagem, manifesto, monorepo e comandos de teste, lint e build |
| [`git.py`](./git.py) | Branch, histórico e status, sem alterar o que o usuário já mudou |
| [`quality.py`](./quality.py) | Executa a verificação descoberta e resume sucesso, falha e ferramenta ausente |

As ferramentas expostas ao modelo estão em [`devtools.py`](/src/agent/tools/devtools.py).

Voltar ao [README do Callidus](/src/agent/README.md) · [automacao-sistema.md](/docs/architecture/automacao-sistema.md)
