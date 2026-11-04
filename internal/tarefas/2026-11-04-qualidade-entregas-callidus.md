# Checklist: qualidade ponta a ponta das entregas do Callidus

Checkpoint da análise da missão de engenharia autônoma do Claude e do caso real «crie um site de culinária».

| Campo | Valor |
|-------|-------|
| Estado | concluída; pendências externas registradas; publicada |
| Criado em | 2026-11-04 |
| Atualizado em | 2026-11-04 |
| Agente / tarefa | Codex — concluir a missão e elevar a qualidade das entregas |
| Regras consultadas | [Hub](/docs/regras/README.md), [Engenharia](/docs/engineering/README.md), [AGENTS.md](/AGENTS.md) §§ 9–19 |

## 🎯 Objetivo

Concluir o que falta da missão «Callidus autonomous engineering platform» sem tocar no trabalho alheio em andamento; usar o run culinário como evidência para reforçar requisitos, verificação independente, recuperação, revisão visual/funcional e comunicação honesta. Entregar também uma versão funcional e polida do exemplo, sem ampliar o escopo para backend ou publicação.

## Próxima ação

Quando a árvore compartilhada estiver sem alterações de execução concorrentes, rodar G1 com baseline e estado atual isolados usando o mesmo modelo. Em seguida, avançar G16 com verificadores específicos para documentos, planilhas, dados e interfaces. O caso culinário e as correções independentes da missão Claude estão concluídos.

## 🔄 Etapas

- [x] 2026-11-04 — Ler ROADMAP, gaps, STATUS, plano, hub de regras e auditorias de engenharia.
- [x] 2026-11-04 — Inspecionar `data/agent.db` em modo somente leitura e examinar a conversa e o artefato culinário.
- [x] 2026-11-04 — Identificar pendências reais da missão Claude: G1 real, handoff na UI, roteamento de consultas por especialidade.
- [x] Formalizar o padrão de qualidade ponta a ponta e os limites por tipo de entrega.
- [x] Reprovar evidência de uma etapa de arquivo quando ela não cobre o arquivo pedido explicitamente.
- [x] Cobrir a regressão com testes determinísticos sem tocar nos testes existentes de outra sessão.
- [x] Ampliar o piso de qualidade de projetos web com critérios claros e proporcionais ao pedido.
- [x] Selecionar critérios iniciais por formato de entrega (documento, planilha, apresentação e pesquisa) sem tratar o prompt como verificação real.
- [x] Melhorar o site culinário local: hierarquia visual, responsividade, busca/filtros, favoritos, detalhes e formulário com feedback real.
- [x] Validar o site no navegador em desktop e mobile; corrigir falhas de console, links, imagens e controles.
- [x] Concluir as pendências da missão Claude independentes e verificáveis: handoff na UI e roteamento lexical por especialidade.
- [x] Atualizar documentação, índices, gaps, checklist, `resume.md` e `plan/STATUS.md`.
- [x] Rodar as verificações aplicáveis; registrar comandos e resultados observados.
- [x] Rodar `.venv/bin/python scripts/resume.py check` e `.venv/bin/python scripts/ci.py`; registrar bloqueios abaixo.
- [x] Revisão final, commit apenas dos caminhos desta tarefa e push após validação isolada.

## 📁 Arquivos previstos

| Caminho | Por quê | Fase | Como |
|---------|---------|------|------|
| `internal/tarefas/2026-11-04-qualidade-entregas-callidus.md` | checkpoint retomável da análise e execução | planejamento → finalização | registrar achados, decisões, verificações e próximo passo |
| `plan/STATUS.md` | posse e retomada em ambiente compartilhado | durante | registrar esta sessão e liberar posse no fim |
| `src/agent/orchestrator/global_verify.py` | impedir aceite de etapa de arquivo com evidência em arquivo diferente | correção | validar nome de artefato explicitamente pedido contra evidência atual |
| `tests/test_global_acceptance.py` ou novo teste dedicado | reproduzir a falha sem depender do modelo ou da rede | correção | fixture de tarefa + evidência apontando para arquivo errado |
| `src/agent/orchestrator/quality_contract.py` | classificar pedidos de site e explicitar critérios web | planejamento/execução | piso inferido, com método de verificação, sem inventar backend |
| `tests/test_quality_disposition.py` | proteger a classificação e o contrato web | planejamento/execução | casos curtos em português e preservação de escopo |
| `docs/engineering/delivery-quality.md` e índices relacionados | tornar o método reutilizável para qualquer categoria de trabalho | documentação | contrato de entrega, matriz evidência→claim, revisão e recuperação |
| `src/agent/services/query_service.py` e `web/static/assets/app/components/intelligence-organization.js` | concluir as duas pendências de engenharia de organização independentes de G1 | continuação Claude | ordenação por especialidade; mostrar handoff persistido no detalhe |
| `docs/progresso/` e `docs/engineering/final-audit.md` | manter fila, avaliação, checklist e auditoria coerentes com o estado real | documentação | registrar G16, resultados verificados e limites restantes |
| `/Users/hidekinishida/Documents/Projetos/site exemplo 3/` | demonstrar o padrão no artefato que originou a auditoria | aplicação | HTML, CSS e JS locais; sem backend nem publicação |

## 🧠 Contexto e decisões

- 2026-11-04: a conversa mais recente do Callidus foi concluída como sucesso, mas a tarefa `Criar style.css` alterou `index.html`; a evidência genérica `file_contains` não detectou a divergência.
- 2026-11-04: o run registrou duas reprovações de verificação, dois replanejamentos e uma tentativa de listar arquivos; mesmo assim a raiz ficou `COMPLETED`, com apenas `index.html` no projeto.
- 2026-11-04: controles do exemplo não tinham comportamento (`Veja Todas`, envio do formulário), não havia CSS ou JS externos, imagens dependiam de URLs remotas não verificadas e não houve prova de navegação em browser.
- 2026-11-04: a missão Claude já está implementada em commits `c21bbe8`, `4d4aa38`, `550d733`; pendências documentadas: medição real G1, handoff na aba Organização, roteamento de consulta por especialidade (G7).
- Não mexer nos 16 arquivos modificados já existentes nem no banco real. A inspeção do banco foi somente leitura. O site de exemplo é uma pasta de projeto separada, alterada somente para produzir uma demonstração melhor.
- Não adicionar dependências. Não trocar provedor/modelo padrão. Não publicar versão.

## 🧪 Verificações

- Teste determinístico da evidência com nome de arquivo divergente.
- Testes de contrato web e de herança de critérios.
- Navegador real em desktop e mobile: navegação, busca, filtro, favorito, detalhe, envio inválido/válido, console e requisições.
- `python scripts/resume.py check`.
- `python scripts/ci.py` (a suíte pode sinalizar falhas preexistentes nas mudanças locais não pertencentes a esta tarefa; discriminar a causa sem editar os arquivos correspondentes).

Resultados de 2026-11-04:

- `.venv/bin/python -m pytest tests/test_global_acceptance.py tests/test_quality_disposition.py tests/test_query_service.py tests/test_organization_api.py -q`: **61 passaram** (após incluir os perfis de documento, planilha, apresentação e pesquisa).
- `node --test tests/web/organization.test.mjs`: **4 passaram**; `node --check web/static/assets/app/components/intelligence-organization.js`: passou.
- Navegador Playwright em `http://127.0.0.1:8769/`: título e conteúdo carregados; imagens observadas carregadas; 0 mensagens de console; `scrollWidth == innerWidth` em 390 px e desktop; busca, filtros, favoritos persistidos, diálogo de receita e feedback explícito do formulário já exercitados.
- `.venv/bin/python scripts/resume.py check`: passou depois de atualizar o índice vivo.
- `.venv/bin/python scripts/ci.py` na árvore compartilhada: **1488 passaram, 1 falhou** em `tests/test_multirequisito_regressions.py::test_edit_file_with_empty_old_string_appends`, cuja edição em `src/agent/tools/builtins.py` é trabalho preexistente de outra sessão.
- `.venv/bin/python scripts/ci.py --rapido` na árvore compartilhada: todos os portões passaram após sincronizar `resume.md`.
- Cópia temporária limpa do `HEAD` com somente os arquivos staged desta entrega: `.venv/bin/python scripts/ci.py` passou em todos os portões, incluindo resume, E2E e suíte Python. A cópia tinha dependências locais ligadas por symlink e foi descartada após a verificação.
- Commits `7b45f9a` (correção sistêmica), `3fbe038` (checkpoint) e `74bf9fe` (perfis para artefatos e inventário limpo) publicados em `origin/main`.
- Verificadores individuais de Markdown, links, referências e resume passaram.
- G1 não foi rodado: o script/execução contém trabalho compartilhado não commitado, portanto não havia baseline isolado comparável para atribuir o resultado.

## 🔀 Plano B

Se a avaliação do modelo local estiver indisponível ou depender de modelo que não está instalado, não trocar a configuração: registrar a limitação e concluir a regressão com fixture determinística. Se a verificação global não puder ser ampliada sem tocar em área atualmente possuída por outra sessão, entregar a regra numa nova unidade isolada e registrar a integração pendente sem fazer um falso aceite.

## Bloqueios

- 16 arquivos com mudanças pré-existentes e sem posse desta tarefa; permanecem intocados.
- Avaliação real G1 pode depender de um servidor/modelo Ollama ativo.

## Artefatos

| Path | Notas |
|------|-------|
| `internal/tarefas/2026-11-04-qualidade-entregas-callidus.md` | análise, plano, progresso e evidências |
| `/Users/hidekinishida/Documents/Projetos/site exemplo 3/` | demonstração local do contrato web |

## Notas de retomada

O banco `data/agent.db` foi aberto em `mode=ro`. Conversa `552c66fe7d034cc39042df04c1678ffe`, tarefa raiz `f5954357a7004403be77fc9dabd2a8f7`. Primeiro consertar a lacuna de validação sem reformatar/descartar as alterações locais. Depois implementar a página demonstração e auditar o fluxo real no navegador.
