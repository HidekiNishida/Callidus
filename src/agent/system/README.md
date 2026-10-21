# `src/agent/system/` — Adaptadores de sistema

Comandos nativos e diagnóstico do computador, com uma interface só para o agente.

| Módulo | Papel |
|--------|-------|
| [`adapters.py`](./adapters.py) | `MacAdapter`, `WindowsAdapter`, `LinuxAdapter`: o comando de cada plataforma, sem fingir suporte |
| [`processes.py`](./processes.py) | Listar, inspecionar, encerrar e acompanhar subprocessos |
| [`apps.py`](./apps.py) | Descobrir e abrir aplicativos, arquivos, pastas e URLs |
| [`platform_info.py`](./platform_info.py) | Sistema, sessão gráfica, permissões e dependências |

O adaptador monta o comando. Quem executa é a ferramenta, depois da política do registro.
Matriz do que cada sistema faz: [automacao-sistema.md](/docs/architecture/automacao-sistema.md).

Voltar ao [README do Callidus](/src/agent/README.md)
