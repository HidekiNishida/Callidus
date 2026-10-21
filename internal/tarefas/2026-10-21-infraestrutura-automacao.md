# Checklist: Infraestrutura de automação, ferramentas e skills

| Campo | Valor |
|-------|-------|
| Estado | concluída |
| Criado em | 2026-10-21 |
| Atualizado em | 2026-10-21 |
| Agente / tarefa | Infraestrutura universal de automação, ferramentas de sistema e skills autorais |
| Regras consultadas | [Hub](/docs/regras/README.md), [validacoes-testes.md](/docs/regras/validacoes-testes.md), [documentacao.md](/docs/regras/documentacao.md), [verificacao-final.md](/docs/regras/verificacao-final.md) |

## 🎯 Objetivo

O Callidus escolhe ferramentas com contrato, age no computador e no projeto dentro da
política de risco, e cria uma skill que passa por validação e teste antes de ser usada.

## Próxima ação

Nenhuma. A aba Ferramentas foi conferida em `http://127.0.0.1:8766` (processo temporário, já encerrado). O processo que já escutava em `8765` continua o anterior e precisa de reinício para servir as rotas novas.

## 🔄 Etapas

- [x] Auditoria do código já escrito e sem checklist (registro, sistema, desktop, engenharia, skills, testes)
- [x] Validação de argumentos no registro, antes do handler
- [x] Acessibilidade: listar, esperar e clicar pelo nome, com diagnóstico quando a permissão falta
- [x] Navegador: preencher, capturar, ária, console e rede, sem devolver senha nem cabeçalho
- [x] Aba Ferramentas mostra diagnóstico, dependências ausentes e skills
- [x] Testes: 856 passaram, 1 ignorado; `node --test tests/web/tools-report.test.mjs` passou
- [x] Documentação: [automacao-sistema.md](/docs/architecture/automacao-sistema.md)
- [x] `resume.md` sincronizado (`python3 scripts/resume.py check` em dia; 2536 itens carimbados)
- [x] Aba Ferramentas conferida no navegador: diagnóstico do macOS, 80 ferramentas, famílias e a frase de dependências
- [x] Commit e push

## Bloqueios

- Captura de tela neste Mac: Screen Recording não concedida ao processo. A ferramenta explica.
- Árvore de acessibilidade neste Mac: System Events devolve `-10000`. A ferramenta pede Automação e Accessibility.
- Windows e Linux: adaptadores implementados, não executados neste ambiente.

## Artefatos

| Path absoluto | Notas |
|---------------|-------|
| `/docs/architecture/automacao-sistema.md` | Matriz, política, famílias e como testar |
| `/src/agent/tools/arguments.py` | Validação de argumentos |
| `/src/agent/desktop/accessibility.py` | Árvore de acessibilidade |
| `/lab/demo_app.py` | Aplicativo descartável do fluxo de integração |
| `/internal/tarefas/2026-10-21-infraestrutura-automacao.md` | este checklist |

## Notas de retomada

O grosso da infraestrutura já estava no disco, sem commit e sem este checklist.
A continuação fechou validação, acessibilidade, ações de página, o resumo da aba
Ferramentas e a documentação. A suíte completa passou fora do sandbox (processos e
`git init` falham dentro dele).
