# Execução em computador remoto

O projeto rodando em outro computador, por SSH.

Voltar ao [Hub](/docs/architecture/README.md) · Configuração: [provedores.md](/docs/architecture/provedores.md)

Um projeto pode rodar em **outro computador** (servidor Linux, macOS ou Windows). Com isso, os
comandos, leituras, escritas e listagens do projeto são executados no servidor — o Callidus
continua rodando na sua máquina.

## ⚙️ Como configurar

Na interface: **Ajustes → Projetos → ícone de servidor** (ou a API `PUT /projects/{id}/remote`).

| Campo | Significado | Exemplo |
|-------|-------------|---------|
| `host` | Endereço do servidor | `servidor.exemplo` |
| `port` | Porta do SSH | `22` |
| `user` | Usuário do login | `deploy` |
| `key_path` | Chave SSH privada | `~/.ssh/id_ed25519` |
| `root` | Pasta do projeto no servidor | `/srv/app` |
| `shell` | `posix` (Linux/macOS) ou `powershell` (Windows) | `posix` |
| `timeout` | Tempo limite de cada comando (s) | `120` |

O botão **Testar conexão** confirma o acesso antes de salvar (roda `uname -s` no POSIX e
`$PSVersionTable` no PowerShell). **Usar máquina local** remove a configuração.

## 🧠 Como funciona

| Peça | Papel |
|------|-------|
| [`src/agent/remote/ssh.py`](/src/agent/remote/ssh.py) | Transporte: fala com o servidor pelo binário `ssh` do sistema (sem dependência extra) |
| [`src/agent/remote/tools.py`](/src/agent/remote/tools.py) | Ferramentas remotas: ler, escrever, listar, editar, remover, mover, buscar |
| [`src/agent/tools/registry.py`](/src/agent/tools/registry.py) | `ToolContext.remote` — quando presente, as ferramentas vão para o servidor |
| [`src/agent/persistence/models.py`](/src/agent/persistence/models.py) | `project_remotes` — a configuração por projeto |

Regras:

1. **Caminho relativo obrigatório**: o agente trabalha dentro de `root`; caminho absoluto ou com
   `..` é recusado (mesma trava do modo local).
2. **Comandos**: `ssh -p <porta> -i <chave> usuário@host "cd <pasta> && <comando>"`, com a saída
   transmitindo em tempo real (aparece no chat como “Comando”).
3. **Arquivos**: `cat`, `printf | base64 -d >` e `ls` no POSIX; `Get-Content`,
   `[IO.File]::WriteAllBytes` e `Get-ChildItem` no PowerShell.
4. **Sem senha no comando**: use chave SSH. A senha não é guardada pela interface.

## 🧠 O que continua local

- O agente, o modelo e a memória rodam na máquina do Callidus.
- O **diff** e os eventos de arquivo são calculados localmente a partir do que o servidor devolve.
- O `git-diff` do projeto usa o repositório local (o remoto não é inspecionado por Git).

## ⚠️ Limitações conhecidas

1. A configuração é por projeto; não há “grupo de servidores”.
2. Sem SFTP: arquivos transferem por `base64` no canal SSH (bem para arquivos de texto; arquivos
   muito grandes pesam).
3. `glob` e `grep` remotos são feitos por `find`/`grep` (POSIX) e `Get-ChildItem`/`Select-String`
   (Windows) — sem as mesmas sutilezas do `pathlib`.
4. A chave SSH precisa existir na máquina do Callidus e estar sem senha (ou o agente SSH na
   verdade, por exemplo).

Voltar: [architecture/README.md](/docs/architecture/README.md)