# Execução Remota (`remote/`) — Projeto em Outro Computador

Transporte das ações de um projeto (comandos, leituras, escritas) quando o projeto roda em
outro computador por **SSH**.

## Arquivos

| Arquivo | Responsabilidade |
|---------|------------------|
| [`ssh.py`](ssh.py) | Cliente SSH: executa comando no servidor e devolve saída e código de saída; monta a pasta remota do projeto |
| [`tools.py`](tools.py) | Ferramentas de execução remota expostas ao modelo (quando o projeto tem computador remoto configurado) |

## Dependências permitidas

- `agent.services.project_service` — a configuração do remoto é persistida por projeto.
- `paramiko`/`ssh` — transporte real; a configuração vem de `RemoteConfig`.

## Restrições

- A configuração remota (`host`, porta, usuário, chave, pasta) fica no banco do projeto; a
  chave **nunca** é gravada em log nem devolvida pela API.
- O comando executado é sempre montado a partir da raiz remota do projeto — o agente não
  escreve fora dela.

## Testes

```bash
pytest tests/test_remote_ssh.py -v
```

---

**Voltar:** [src/agent/README.md](../README.md) · **Raiz:** [README.md](../../../README.md)
