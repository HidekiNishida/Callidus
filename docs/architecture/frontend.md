# Interface web

Estáticos em [`web/static/`](/web/static/). Servidos pela API em `/` quando a pasta existe.

| Área | Função |
|------|--------|
| Projetos | Criar e selecionar workspace |
| Tarefas | Árvore textual de estados |
| Execução | Iniciar run, passo único, executar até idle |
| Eventos | JSON dos últimos eventos |

Requer API em `http://127.0.0.1:8765` (mesma origem). Para demo E2E no UI, use objetivo contendo `e2e` e `root_path` apontando para uma cópia de `tests/fixtures/sample_project/`.
