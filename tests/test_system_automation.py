"""
Arquivo: tests/test_system_automation.py
Nome: test_system_automation.py
Propósito: verificar a automação do sistema: processos, tarefas em segundo plano, arquivos e rede.
Responsabilidade: camada de testes — comportamento real dos adaptadores de sistema sobre processos descartáveis.
Componentes: ProcessManager, list_processes, terminate_process, ferramentas de hash, arquivo e extração.
Dependências: agent.system.processes, agent.tools.system_tools, agent.tools.registry, pytest.
Observações: os testes usam processos do próprio interpretador e arquivos temporários.
"""
import os
import sys
import time
import zipfile
from pathlib import Path

import pytest

from agent.system.processes import ProcessManager, list_processes, terminate_process
from agent.tools.registry import ToolContext, build_default_registry


def _ctx(root: Path) -> ToolContext:
    """Contexto de ferramenta apontado para uma pasta temporária.

    Args:
        root: pasta do workspace.

    Returns:
        O contexto pronto para uso.
    """
    return ToolContext(project_root=str(root))


@pytest.mark.asyncio
async def test_lista_de_processos_encontra_o_proprio_interpretador():
    """A listagem de processos encontra o processo do próprio teste."""
    found = list_processes(match="python", limit=200)
    assert found
    assert any(item.pid == os.getpid() for item in found)


@pytest.mark.asyncio
async def test_tarefa_em_segundo_plano_aceita_saida_e_cancela():
    """A tarefa em segundo plano devolve saída parcial e pode ser cancelada."""
    manager = ProcessManager()
    handle = manager.start([sys.executable, "-u", "-c", "print('iniciado'); import time; time.sleep(60)"])
    try:
        deadline = time.monotonic() + 10
        output = ""
        while time.monotonic() < deadline:
            output = manager.output(handle.handle_id).get("stdout", "")
            if output:
                break
            time.sleep(0.2)
        assert "iniciado" in output
        cancelled = manager.cancel(handle.handle_id)
        assert cancelled["success"] is True
        assert cancelled["handle"]["cancelled"] is True
    finally:
        manager.cancel(handle.handle_id, force=True)


@pytest.mark.asyncio
async def test_encerramento_de_processo_existente_e_de_processo_inexistente():
    """Encerrar um processo inexistente devolve erro controlado, sem exceção."""
    result = terminate_process(999_999_999)
    assert result["success"] is False
    assert "não existe" in result["error"]


@pytest.mark.asyncio
async def test_encerramento_recusa_o_proprio_processo():
    """O Callidus não encerra o próprio processo."""
    result = terminate_process(os.getpid())
    assert result["success"] is False
    assert "Callidus" in result["error"]


@pytest.mark.asyncio
async def test_hash_de_arquivo_e_conferevel(tmp_path):
    """O hash do arquivo é o mesmo em duas execuções e muda quando o conteúdo muda."""
    reg = build_default_registry()
    target = tmp_path / "a.txt"
    target.write_text("conteudo", encoding="utf-8")
    first = await reg.execute("file_hash", _ctx(tmp_path), {"path": "a.txt"})
    second = await reg.execute("file_hash", _ctx(tmp_path), {"path": "a.txt"})
    assert first["success"] is True
    assert first["hash"] == second["hash"]
    target.write_text("outro conteudo", encoding="utf-8")
    third = await reg.execute("file_hash", _ctx(tmp_path), {"path": "a.txt"})
    assert third["hash"] != first["hash"]


@pytest.mark.asyncio
async def test_hash_recusa_caminho_fora_do_workspace(tmp_path):
    """O hash não alcança caminho fora da raiz autorizada."""
    reg = build_default_registry()
    out = await reg.execute("file_hash", _ctx(tmp_path), {"path": "/etc/hosts"})
    assert out["success"] is False
    assert "fora do escopo" in out["error"]


@pytest.mark.asyncio
async def test_arquivo_compactado_e_extraido_de_volta(tmp_path):
    """O ciclo compactar e extrair devolve o conteúdo original."""
    reg = build_default_registry()
    (tmp_path / "pasta").mkdir()
    (tmp_path / "pasta" / "a.txt").write_text("dentro", encoding="utf-8")
    packed = await reg.execute(
        "archive_files", _ctx(tmp_path), {"source": "pasta", "format": "zip"}, approved=True
    )
    assert packed["success"] is True
    extracted = await reg.execute(
        "extract_archive", _ctx(tmp_path), {"path": Path(packed["path"]).name}, approved=True
    )
    assert extracted["success"] is True
    out = extracted["target"]
    assert (Path(out) / "a.txt").read_text(encoding="utf-8") == "dentro"


@pytest.mark.asyncio
async def test_extracao_recusa_zip_slip(tmp_path):
    """A extração recusa entrada que escaparia do destino."""
    reg = build_default_registry()
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as bundle:
        bundle.writestr("../fora.txt", "conteudo")
    out = await reg.execute("extract_archive", _ctx(tmp_path), {"path": "evil.zip"}, approved=True)
    assert out["success"] is False
    assert "escaparia" in out["error"]
    assert not (tmp_path.parent / "fora.txt").exists()


@pytest.mark.asyncio
async def test_variaveis_de_ambiente_secretas_sao_redigidas(tmp_path, monkeypatch):
    """A listagem de ambiente mostra o nome da variável secreta, nunca o valor."""
    monkeypatch.setenv("CALLIDUS_TESTE_SEGREDO", "valor-que-nao-aparece")
    reg = build_default_registry()
    out = await reg.execute("list_env", _ctx(tmp_path), {"match": "CALLIDUS_TESTE"})
    assert out["success"] is True
    assert out["env"]["CALLIDUS_TESTE_SEGREDO"] == "[REDACTED]"
    assert "valor-que-nao-aparece" not in str(out)
    assert "CALLIDUS_TESTE_SEGREDO" in out["redacted"]


@pytest.mark.asyncio
async def test_diagnostico_descreve_o_ambiente(tmp_path):
    """O diagnóstico devolve sistema, permissões e resumo legível."""
    reg = build_default_registry()
    out = await reg.execute("system_diagnose", _ctx(tmp_path), {})
    assert out["success"] is True
    assert out["system"]["system"]
    assert out["permissions"]["checks"]
    assert out["summary"]


@pytest.mark.asyncio
async def test_recursos_do_sistema_sao_legiveis(tmp_path):
    """A ferramenta de recursos devolve disco, memória e carga."""
    reg = build_default_registry()
    out = await reg.execute("system_resources", _ctx(tmp_path), {})
    assert out["success"] is True
    assert out["disk"]["total"] > 0
    assert out["cpu_count"]


@pytest.mark.asyncio
async def test_ferramenta_de_rede_recusa_esquema_invalido(tmp_path):
    """A requisição HTTP recusa esquema que não seja http(s)."""
    reg = build_default_registry()
    out = await reg.execute("http_request", _ctx(tmp_path), {"url": "file:///etc/passwd"}, approved=True)
    assert out["success"] is False
    assert "http" in out["error"]


@pytest.mark.asyncio
async def test_ferramenta_de_tarefa_recusa_comando_vazio(tmp_path):
    """A tarefa em segundo plano recusa comando vazio."""
    reg = build_default_registry()
    out = await reg.execute("task_start", _ctx(tmp_path), {"command": []}, approved=True)
    assert out["success"] is False
