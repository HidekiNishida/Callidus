# `src/agent/desktop/` — Tela, entrada e acessibilidade

Automação da sessão gráfica. A árvore de acessibilidade vem antes da coordenada.

| Módulo | Papel |
|--------|-------|
| [`capabilities.py`](./capabilities.py) | Geometria da tela e captura |
| [`windows.py`](./windows.py) | Janelas visíveis |
| [`accessibility.py`](./accessibility.py) | Elementos por nome e papel; espera; clique no centro relido na hora |
| [`input.py`](./input.py) | Clique, arrasto, tecla, texto e rolagem |

Sem sessão gráfica, sem permissão de Accessibility ou sem Screen Recording, a função
devolve o erro e a permissão que falta. Wayland não herda as capacidades do X11.

Voltar ao [README do Callidus](/src/agent/README.md) · [automacao-sistema.md](/docs/architecture/automacao-sistema.md)
