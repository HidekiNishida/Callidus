# tests/test_remote_ssh.py — execução remota por SSH (com binário ssh falso)
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from agent.api import deps
from agent.config import Settings
from agent.remote.ssh import RemoteConfig, RemoteError, SshTransport


@pytest.fixture
def fake_ssh(tmp_path: Path, monkeypatch):
    """Binário `ssh` falso: registra os argumentos e devolve uma saída programada."""
    log = tmp_path / "args.log"
    out = tmp_path / "out.txt"
    out.write_text("Linux\n", encoding="utf-8")
    script = tmp_path / "ssh"
    script.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$@" > "$SSH_FAKE_LOG"\n'
        'cat "$SSH_FAKE_OUT" 2>/dev/null\n'
        "exit ${SSH_FAKE_CODE:-0}\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("SSH_FAKE_LOG", str(log))
    monkeypatch.setenv("SSH_FAKE_OUT", str(out))
    monkeypatch.setattr("agent.remote.ssh.shutil.which", lambda name: str(script))
    return log


def test_comando_posix_via_ssh(fake_ssh):
    transport = SshTransport(RemoteConfig(host="servidor.exemplo", user="deploy", root="/srv/app"))
    result = transport._base_args()
    joined = " ".join(result)
    assert "deploy@servidor.exemplo" in joined
    assert "-p" in result and "22" in result
    assert "BatchMode=yes" in joined


def test_caminho_remoto_monta_a_pasta_do_projeto():
    posix = SshTransport(RemoteConfig(host="h", root="/srv/app"))
    assert posix._remote_path("a/b.txt") == "/srv/app/a/b.txt"
    assert posix._remote_path(".") == "/srv/app"
    win = SshTransport(RemoteConfig(host="h", root="C:\\app", shell="powershell"))
    assert win._remote_path("a/b.txt") == "C:\\app\\a\\b.txt"


@pytest.mark.asyncio
async def test_run_monta_o_cd_e_manda_o_comando(fake_ssh):
    transport = SshTransport(RemoteConfig(host="h", user="deploy", root="/srv/app"))
    await transport.run(["pytest", "-q"], cwd="tests")
    args = fake_ssh.read_text(encoding="utf-8")
    assert "cd /srv/app/tests && pytest -q" in args


@pytest.mark.asyncio
async def test_run_powershell_usa_set_location(fake_ssh):
    transport = SshTransport(RemoteConfig(host="h", root="C:\\app", shell="powershell"))
    await transport.run("npm test", cwd=".")
    args = fake_ssh.read_text(encoding="utf-8")
    assert "Set-Location -LiteralPath" in args
    assert "npm test" in args


@pytest.mark.asyncio
async def test_check_devolve_o_sistema(fake_ssh):
    transport = SshTransport(RemoteConfig(host="h"))
    result = await transport.check()
    assert result["ok"] is True
    assert "Linux" in result["system"]


@pytest.mark.asyncio
async def test_chave_inexistente_vira_erro_claro(fake_ssh, tmp_path: Path):
    transport = SshTransport(RemoteConfig(host="h", key_path=str(tmp_path / "nao-existe")))
    with pytest.raises(RemoteError) as exc:
        transport._base_args()
    assert "chave SSH" in str(exc.value)


def test_config_invalida_e_rejeitada():
    with pytest.raises(Exception):
        RemoteConfig(host="")


def test_projeto_guarda_e_remove_o_computador_remoto(tmp_path: Path, monkeypatch):
    from fastapi.testclient import TestClient

    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)

    def override_settings():
        return settings

    deps._engine = None
    deps._session_factory = None
    from agent.api.main import app

    app.dependency_overrides[deps.read_settings] = override_settings
    with TestClient(app) as client:
        project = client.post("/projects", json={"name": "remoto", "root_path": str(tmp_path)}).json()
        assert client.get(f"/projects/{project['id']}/remote").json()["remote"] is None

        saved = client.put(
            f"/projects/{project['id']}/remote",
            json={
                "host": "servidor.exemplo",
                "port": 2222,
                "user": "deploy",
                "root": "/srv/app",
                "shell": "posix",
            },
        )
        assert saved.status_code == 200, saved.text
        remote = client.get(f"/projects/{project['id']}/remote").json()["remote"]
        assert remote["host"] == "servidor.exemplo"
        assert remote["port"] == 2222
        assert remote["root"] == "/srv/app"

        removed = client.delete(f"/projects/{project['id']}/remote")
        assert removed.status_code == 200
        assert client.get(f"/projects/{project['id']}/remote").json()["remote"] is None
    app.dependency_overrides.clear()
    deps._engine = None
    deps._session_factory = None


def test_teste_de_conexao_sem_configuracao(tmp_path: Path):
    from fastapi.testclient import TestClient

    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)

    def override_settings():
        return settings

    deps._engine = None
    deps._session_factory = None
    from agent.api.main import app

    app.dependency_overrides[deps.read_settings] = override_settings
    with TestClient(app) as client:
        project = client.post("/projects", json={"name": "sem-remoto", "root_path": str(tmp_path)}).json()
        response = client.post(f"/projects/{project['id']}/remote/test")
        assert response.status_code == 400
        assert "remoto" in response.json()["detail"]
    app.dependency_overrides.clear()
    deps._engine = None
    deps._session_factory = None


@pytest.mark.asyncio
async def test_comando_da_ferramenta_vai_para_o_servidor_remoto(fake_ssh, tmp_path: Path):
    """Com projeto remoto, a ferramenta de comando roda no servidor (e não na máquina local)."""
    from agent.tools.builtins import _run_command
    from agent.tools.registry import ToolContext

    ctx = ToolContext(
        project_root=str(tmp_path),
        remote=RemoteConfig(host="h", user="deploy", root="/srv/app"),
    )
    result = await _run_command(ctx, {"command": "echo ola", "timeout": 20})
    args = fake_ssh.read_text(encoding="utf-8")
    assert "deploy@h" in args
    assert "echo ola" in args
    assert result["success"] is True
    assert result["remote"] is True


@pytest.mark.asyncio
async def test_leitura_de_arquivo_vai_para_o_servidor_remoto(fake_ssh, tmp_path: Path):
    """Com projeto remoto, a leitura de arquivo busca o conteúdo no servidor."""
    from agent.tools.builtins import _read_file
    from agent.tools.registry import ToolContext

    out = tmp_path / "out.txt"
    out.write_text("conteudo remoto\n", encoding="utf-8")
    ctx = ToolContext(
        project_root=str(tmp_path),
        remote=RemoteConfig(host="h", root="/srv/app"),
    )
    result = await _read_file(ctx, {"path": "notas.txt"})
    assert result["success"] is True
    assert "conteudo remoto" in result["content"]
    assert result["remote"] is True


@pytest.mark.asyncio
async def test_caminho_fora_do_projeto_e_recusado_no_remoto(fake_ssh, tmp_path: Path):
    from agent.tools.builtins import _read_file
    from agent.tools.registry import ToolContext

    ctx = ToolContext(
        project_root=str(tmp_path),
        remote=RemoteConfig(host="h", root="/srv/app"),
    )
    result = await _read_file(ctx, {"path": "/etc/passwd"})
    assert result["success"] is False
    assert "fora do projeto" in result["error"]
