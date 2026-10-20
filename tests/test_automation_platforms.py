"""
Arquivo: tests/test_automation_platforms.py
Nome: test_automation_platforms.py
Propósito: Verificar os três adaptadores de serviço do supervisor de automações.
Responsabilidade: camada de testes — arquivo gerado, argumentos montados e decisões de cada adaptador de sistema operacional.
Componentes: launchd com arranque e recuperação, instalação por usuário, unidade systemd de usuário, privilégio administrativo, remoção, agendador de tarefas do Windows, status e seleção de adaptador.
Dependências: agent.automation.service e agent.automation.cli.
Observações: HOME redirecionado para tmp_path e comandos do sistema operacional substituídos por dublês; nenhuma execução real de serviço.

Testes dos três adaptadores de serviço.

O ambiente de execução pode ser um só: os adaptadores são testados por **unidade**
(arquivo gerado, argumentos montados, decisões) e por simulação do sistema
operacional. Nenhum teste aqui afirma que um serviço do Windows ou do Linux foi
validado em execução nesta máquina — o que se comprova é o comando e o arquivo
produzidos.
"""

from __future__ import annotations

import plistlib
from pathlib import Path


from agent.automation.service import (
    LaunchdAdapter,
    ServiceOptions,
    SystemdAdapter,
    WindowsTaskAdapter,
    adapters_status,
    current_adapter,
    default_options,
)


# ─────────────────────────────────────────────────────────── macOS

def test_launchd_gera_plist_com_arranque_e_recuperacao(tmp_path, monkeypatch):
    """O plist gerado carrega o label, o arranque automático, a recuperação e as variáveis de ambiente."""
    monkeypatch.setenv("HOME", str(tmp_path))
    adapter = LaunchdAdapter()
    options = ServiceOptions(
        command=["/usr/bin/python3", "-m", "agent.automation.cli", "run"],
        working_dir=str(tmp_path),
        log_path=str(tmp_path / "supervisor.log"),
        env={"CALLIDUS_DATA_DIR": str(tmp_path / "data")},
    )
    monkeypatch.setattr(adapter, "available", lambda: True)
    monkeypatch.setattr(adapter, "_run", lambda *a, **k: (0, "", ""))
    result = adapter.install(options)
    assert result["installed"] is True
    path = Path(result["path"])
    assert path.exists()
    payload = plistlib.loads(path.read_bytes())
    assert payload["Label"] == "com.callidus.supervisor"
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] is True
    assert payload["ProgramArguments"][-1] == "run"
    assert payload["EnvironmentVariables"]["CALLIDUS_DATA_DIR"].endswith("data")

    # A remoção apaga o arquivo.
    adapter.uninstall()
    assert not path.exists()


def test_launchd_instalacao_por_usuario_nao_exige_administrador(tmp_path, monkeypatch):
    """A instalação por usuário do launchd é aceita e fica dentro do diretório do usuário."""
    monkeypatch.setenv("HOME", str(tmp_path))
    adapter = LaunchdAdapter()
    monkeypatch.setattr(adapter, "available", lambda: True)
    monkeypatch.setattr(adapter, "_run", lambda *a, **k: (0, "", ""))
    result = adapter.install(ServiceOptions(scope="user"))
    assert result["installed"] is True
    assert str(tmp_path) in result["path"]


# ─────────────────────────────────────────────────────────── Linux

def test_systemd_gera_unidade_de_usuario(tmp_path, monkeypatch):
    """A unidade systemd de usuário traz o ExecStart, o Restart e o alvo do usuário."""
    monkeypatch.setenv("HOME", str(tmp_path))
    adapter = SystemdAdapter()
    monkeypatch.setattr(adapter, "available", lambda: True)
    monkeypatch.setattr(adapter, "_ctl", lambda args, scope: (0, "", ""))
    options = ServiceOptions(
        command=["/usr/bin/python3", "-m", "agent.automation.cli", "run"],
        working_dir=str(tmp_path),
        env={"CALLIDUS_DATA_DIR": str(tmp_path / "data")},
        scope="user",
    )
    result = adapter.install(options)
    assert result["installed"] is True
    assert result["scope"] == "user"
    unit = Path(result["path"]).read_text()
    assert "ExecStart=/usr/bin/python3 -m agent.automation.cli run" in unit
    assert "Restart=always" in unit
    assert "WantedBy=default.target" in unit
    assert "Environment=CALLIDUS_DATA_DIR=" in unit


def test_systemd_unidade_de_sistema_exige_administrador(tmp_path, monkeypatch):
    """A instalação de sistema systemd sem privilégio administrativo é recusada com dica."""
    monkeypatch.setenv("HOME", str(tmp_path))
    adapter = SystemdAdapter()
    monkeypatch.setattr(adapter, "available", lambda: True)
    monkeypatch.setattr(adapter, "_ctl", lambda args, scope: (0, "", ""))
    monkeypatch.setattr(adapter, "_is_root", lambda: False, raising=False)
    import os

    monkeypatch.setattr(os, "geteuid", lambda: 501)
    result = adapter.install(ServiceOptions(scope="system"))
    assert result["installed"] is False
    assert "privilégio administrativo" in result["error"]
    assert result["hint"]


def test_systemd_uninstall_remove_a_unidade(tmp_path, monkeypatch):
    """A remoção da unidade systemd apaga o arquivo gerado."""
    monkeypatch.setenv("HOME", str(tmp_path))
    adapter = SystemdAdapter()
    monkeypatch.setattr(adapter, "available", lambda: True)
    monkeypatch.setattr(adapter, "_ctl", lambda args, scope: (0, "", ""))
    adapter.install(ServiceOptions(scope="user"))
    result = adapter.uninstall()
    assert result["removed"] is True
    assert not (tmp_path / ".config" / "systemd" / "user" / "callidus-supervisor.service").exists()


# ─────────────────────────────────────────────────────────── Windows

def test_windows_agendador_de_tarefas_registra_tarefa_de_usuario(monkeypatch):
    """A tarefa do Windows é criada por schtasks com disparo no login."""
    adapter = WindowsTaskAdapter()
    monkeypatch.setattr(adapter, "available", lambda: True)
    captured: dict = {}

    def fake_run(args, timeout=60.0):
        """Dublê do comando do sistema: captura os argumentos e devolve sucesso."""
        captured["args"] = args
        return 0, "tarefa criada", ""

    monkeypatch.setattr(adapter, "_run", fake_run)
    result = adapter.install(ServiceOptions(scope="user"))
    assert result["installed"] is True
    assert result["schedule"] == "ONLOGON"
    args = captured["args"]
    assert args[0] == "schtasks"
    assert "/Create" in args
    assert "ONLOGON" in args
    assert "CallidusSupervisor" in args


def test_windows_tarefa_de_sistema_exige_administrador(monkeypatch):
    """A tarefa de sistema do Windows sem privilégio administrativo é recusada."""
    adapter = WindowsTaskAdapter()
    monkeypatch.setattr(adapter, "available", lambda: True)
    monkeypatch.setattr(adapter, "_is_admin", lambda: False)
    result = adapter.install(ServiceOptions(scope="system"))
    assert result["installed"] is False
    assert "privilégio administrativo" in result["error"]


def test_windows_status_de_tarefa_inexistente(monkeypatch):
    """Uma tarefa inexistente aparece como não instalada e inativa no status."""
    adapter = WindowsTaskAdapter()
    monkeypatch.setattr(adapter, "available", lambda: True)
    monkeypatch.setattr(adapter, "_run", lambda args, timeout=60.0: (1, "", "tarefa não existe"))
    status = adapter.status()
    assert status.installed is False
    assert status.active is False
    assert status.platform == "windows"


# ─────────────────────────────────────────────────────────── escolha

def test_adaptador_escolhido_corresponde_a_plataforma(monkeypatch):
    """O adaptador escolhido corresponde à plataforma e o status cobre as três."""
    adapter = current_adapter()
    assert adapter.platform_name in {"macos", "linux", "windows"}
    status = adapters_status()
    assert len(status) == 3
    assert {s["platform"] for s in status} == {"macos", "linux", "windows"}


def test_opcoes_padrao_apontam_para_o_pacote():
    """As opções padrão executam o supervisor do pacote, com escopo de usuário."""
    options = default_options()
    assert options.command[-1] == "run"
    assert "agent.automation.cli" in options.command
    assert options.scope == "user"


def test_cli_tem_os_comandos_de_operacao():
    """A CLI aceita todos os comandos de operação do supervisor."""
    from agent.automation.cli import build_parser

    parser = build_parser()
    for command in ("run", "install", "uninstall", "start", "stop", "status", "diagnose", "list"):
        args = parser.parse_args([command])
        assert args.command == command


def test_cli_install_repassa_o_escopo(tmp_path, monkeypatch):
    """A CLI repassa o escopo informado ao adaptador de instalação."""
    from agent.automation.cli import build_parser, cmd_install

    captured: dict = {}

    class FakeAdapter:
        """Adaptador falso que registra o escopo recebido na instalação."""
        platform_name = "fake"

        def install(self, options):
            """Registra o escopo das opções e devolve instalação bem-sucedida."""
            captured["scope"] = options.scope
            return {"installed": True}

    monkeypatch.setattr("agent.automation.cli.current_adapter", lambda: FakeAdapter())
    parser = build_parser()
    args = parser.parse_args(["install", "--scope", "system"])
    assert cmd_install(args) == 0
    assert captured["scope"] == "system"
