# Automações — runtime de tarefas persistentes

Automações persistentes, autônomas e multiplataforma: o Callidus planeja, grava,
dispara, executa, verifica e recupera tarefas automaticamente.

## 🏗️ As quatro responsabilidades

| Responsabilidade | Onde | O que garante |
|------------------|------|---------------|
| **Definição** | [`store.py`](store.py) + [`contracts.py`](contracts.py) | O contrato aprovado: gatilho, ação, dependências, permissões, política |
| **Disparo** | [`dispatcher.py`](dispatcher.py) | O registro idempotente do disparo e a política de disparos perdidos |
| **Runtime e supervisor** | [`supervisor.py`](supervisor.py) + [`service/`](service/) | O runtime vivo sem a interface e o arranque nativo do sistema |
| **Execução** | [`executor.py`](executor.py) + [`actions/`](actions/) | Dependências → ação → evidência → estado |

## 🏗️ Mapa dos módulos

| Arquivo | Responsabilidade |
|---------|------------------|
| [`enums.py`](enums.py) | Vocabulário: estados, tipos de gatilho, tipos de ação, políticas |
| [`contracts.py`](contracts.py) | Contrato pydantic da definição (versionado) |
| [`timezones.py`](timezones.py) | Fuso, horário de verão, horário local ambíguo ou inexistente |
| [`security.py`](security.py) | Permissões decididas antes do disparo (allowlist, escopo de caminhos, segredos) |
| [`dependencies.py`](dependencies.py) | Verificação e inicialização autorizada de dependências |
| [`triggers/`](triggers/) | Gatilhos temporais (`once`, `cron`, `interval`) e de evento interno |
| [`actions/`](actions/) | Ação Callidus (trabalho do agente) e ação de script (determinística) |
| [`dispatcher.py`](dispatcher.py) | Registro do disparo com chave de idempotência |
| [`executor.py`](executor.py) | Execução do disparo e reconciliação com o run real |
| [`supervisor.py`](supervisor.py) | Runtime autônomo (recupera, dispara, executa, reconcilia) |
| [`service/`](service/) | Adaptadores nativos: `launchd`, `systemd`, Agendador de Tarefas do Windows |
| [`cli.py`](cli.py) | `callidus-supervisor`: rodar, instalar, iniciar, parar, diagnosticar |

## 🔄 Máquina de estados do disparo

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> preparing
    preparing --> running
    preparing --> waiting_dependency
    waiting_dependency --> preparing: dependência voltou
    running --> completed
    running --> failed
    pending --> skipped
    running --> cancelled
    pending --> cancelled
```

- `pending` — aguardando o horário (ou uma nova tentativa, com `next_attempt_at`).
- `preparing` — dependências verificadas, ação a caminho.
- `waiting_dependency` — dependência crítica indisponível; reagendado, sem inferência.
- `running` — a ação está em curso (para a ação Callidus, o run entregue ao worker).
- `completed` / `failed` / `blocked` / `skipped` / `cancelled` — estados finais.

**Registrar o disparo não é concluir a automação.** Uma ação Callidus entrega o run
ao worker e o disparo fica `running`; a reconciliação fecha o estado quando o run
chega a um estado terminal.

## 🔄 Idempotência

A chave de idempotência é única no banco (`automation_firings.idempotency_key`):

- temporal — `auto:<id>:<política>:<instante UTC>`
- evento — `auto:<id>:event:<origem>:<id do evento>`
- manual — `auto:<id>:<tag>:<aleatório>`

Reprocessar o mesmo disparo (reinício, tique duplicado, evento repetido) nunca cria
uma segunda execução equivalente.

## 🛠️ Comandos

```bash
callidus-supervisor run                    # primeiro plano (é o que o serviço executa)
callidus-supervisor install                # instala o serviço nativo (usuário, sem privilégio)
callidus-supervisor install --scope system # nível de sistema (exige administrador)
callidus-supervisor status                 # runtime + serviço nativo
callidus-supervisor diagnose               # automações, próximos disparos, pendências
callidus-supervisor uninstall              # remove o serviço nativo
```

## 📚 Ligações

- [Persistência](/src/agent/persistence/README.md) — tabelas `automations`, `automation_firings`, `automation_events`
- [Serviços](/src/agent/services/README.md) — `scheduler.py` (fachada do agendamento)
- [Arquitetura](/docs/architecture/automacoes.md) — o desenho completo