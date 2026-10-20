# Adaptadores de serviço nativo

![integracoes](/media/icons/integracoes.svg){width=48}

O supervisor das automações precisa rodar **sem a interface aberta**. Cada sistema operacional
tem seu próprio mecanismo de arranque; estes adaptadores traduzem um contrato único para o
mecanismo da plataforma.

| Arquivo | Responsabilidade |
|---------|------------------|
| [`base.py`](base.py) | Contrato `ServiceAdapter` e as operações comuns (instalar, iniciar, parar, uninstall, status) |
| [`launchd.py`](launchd.py) | macOS: LaunchAgent em `~/Library/LaunchAgents` |
| [`systemd.py`](systemd.py) | Linux: unidade `systemd` do usuário |
| [`windows.py`](windows.py) | Windows: Agendador de Tarefas |

## ⚙️ Contrato

O adaptador responde a três perguntas do supervisor: o serviço **está instalado**, **está
rodando** e pode ser **instalado, iniciado, parado e removido**. A plataforma detection
acontece no `supervisor.py`; o `cli.py` (`callidus-supervisor install|uninstall|start|stop|status`)
é a porta de entrada pela linha de comando.

## ⚠️ Cuidados

- Instalação e remoção pedem autorização explícita do usuário.
- O serviço roda com o mesmo ambiente do processo supervisor (mesmo `AGENT_DATA_DIR`).
- Cada adaptador é testado no seu sistema; os demais apenas reportam "não suportado".

**Voltar:** [automation/README.md](../README.md) · **Voltar:** [src/agent/README.md](../../README.md) · [Raiz](/README.md)
