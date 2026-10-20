# Checklist: Automações persistentes, autônomas e multiplataforma

| Campo | Valor |
|-------|-------|
| Estado | concluída |
| Criado em | 2026-10-20 |
| Atualizado em | 2026-10-20 |
| Agente / tarefa | Runtime de automações (definição, disparo, supervisor, execução, adaptadores nativos) |
| Regras consultadas | [Hub](/docs/regras/README.md) |

## 🎯 Objetivo

O Callidus executa tarefas automáticas conforme horários, recorrências, condições e
eventos — independentemente da interface estar aberta — e sobrevive a
reinicializações, indisponibilidade temporária e disparo duplicado.

## Próxima ação

Nada pendente nesta entrega. O serviço nativo ainda precisa ser instalado na máquina
do usuário (`callidus-supervisor install`) para rodar sem a interface.

## 🔄 Etapas

- [x] Auditar o scheduler existente e **reproduzir** as falhas (run sem `root_task_id`,
      `session.get` com string, ciclo de vida da API, `_stop_event` sem loop)
- [x] Corrigir o scheduler e os contratos de persistência (fachada sobre o núcleo novo)
- [x] Implementar a definição persistida e versionada (`automations`)
- [x] Implementar os gatilhos temporais (once, cron, intervalo) com fuso e DST
- [x] Implementar os eventos internos e a entrega idempotente
- [x] Implementar as ações de tarefa Callidus e de script (local e remoto)
- [x] Implementar a verificação e a inicialização autorizada de dependências
- [x] Implementar o despacho idempotente, o executor, as retentativas e a reconciliação
- [x] Implementar o supervisor headless e a CLI (`callidus-supervisor`)
- [x] Implementar os adaptadores nativos: `launchd`, `systemd`, Agendador de Tarefas
- [x] Migrar `scheduled_runs` → `automations` sem apagar a tabela antiga
- [x] Integrar a API e a interface (painel **Automações**)
- [x] Escrever os testes determinísticos (runtime, plataformas, API, ponta a ponta)
- [x] Documentar (README do pacote, doc de arquitetura, READMEs de módulo, README raiz)
- [x] Rodar a suíte determinística completa uma vez no final
- [x] Commit em português

## Bloqueios

- Nenhum no momento.
- **Não comprovado em execução**: o serviço nativo do Windows e o `systemd` (unidade de
  sistema) não foram validados em uma máquina desses sistemas — só por teste de
  unidade e simulação (ver o relatório).

## Artefatos

| Path absoluto | Notas |
|---------------|-------|
| `/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/automation/` | Núcleo: contratos, gatilhos, ações, dependências, despacho, execução, supervisor, CLI, adaptadores |
| `/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/automation/README.md` | Índice do pacote |
| `/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/services/scheduler.py` | Fachada do agendamento (compatibilidade) |
| `/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/persistence/models.py` | `AutomationModel`, `AutomationFiringModel`, `AutomationEventModel` |
| `/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/persistence/database.py` | `migrate_legacy_schedules` (idempotente) |
| `/Users/hidekinishida/Documents/Projetos/Callidus/src/agent/api/automation_routes.py` | Rotas das automações |
| `/Users/hidekinishida/Documents/Projetos/Callidus/web/static/assets/app/components/automations.js` | Painel da interface |
| `/Users/hidekinishida/Documents/Projetos/Callidus/docs/architecture/automacoes.md` | Documento de arquitetura |
| `/Users/hidekinishida/Documents/Projetos/Callidus/tests/test_automation_runtime.py` | 35 regressões do runtime |
| `/Users/hidekinishida/Documents/Projetos/Callidus/tests/test_automation_platforms.py` | Adaptadores das três plataformas |
| `/Users/hidekinishida/Documents/Projetos/Callidus/tests/test_automation_api.py` | HTTP das automações |
| `/Users/hidekinishida/Documents/Projetos/Callidus/tests/test_automation_end_to_end.py` | Fluxo de aceitação |

---

**Regras:** [Hub](/docs/regras/README.md) · **Docs:** [arquitetura](/docs/architecture/README.md) · **Voltar:** [README](/README.md)