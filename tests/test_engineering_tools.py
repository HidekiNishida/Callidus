"""
Arquivo: tests/test_engineering_tools.py
Nome: test_engineering_tools.py
Propósito: verificar a caixa de ferramentas de engenharia: descoberta de projeto, Git e verificações.
Responsabilidade: camada de testes — comportamento da descoberta, do Git e do resumo de resultados.
Componentes: detect_project, discover_commands, read_manifest, git_status/log/branch, run_check.
Dependências: agent.engineering, agent.tools.devtools, pytest.
Observações: os testes usam projetos temporários e um repositório Git descartável.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent.engineering.discovery import detect_project, discover_commands, read_manifest
from agent.engineering.git import git_branch, git_log, git_status, is_repository
from agent.engineering.quality import run_check, summarize_test_output


def _git(root: Path, *args: str) -> None:
    """Executa um comando Git no repositório temporário.

    Args:
        root: pasta do repositório.
        args: argumentos do Git.
    """
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_deteccao_de_projeto_python(tmp_path):
    """Um projeto Python é reconhecido pelo pyproject e pelos testes."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "exemplo"\nversion = "1.0.0"\ndependencies = ["httpx"]\n', encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    info = detect_project(tmp_path)
    assert "python" in info.languages
    assert "pip" in info.package_managers
    assert "pyproject.toml" in info.manifests
    assert "AGENTS.md" not in info.instructions


def test_deteccao_de_projeto_javascript_e_monorepo(tmp_path):
    """Um package.json com workspaces marca o projeto como monorepo."""
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "raiz", "version": "2.0.0", "scripts": {"test": "vitest", "build": "tsc"}}),
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    info = detect_project(tmp_path)
    assert "javascript" in info.languages
    assert "npm" in info.package_managers
    commands = discover_commands(tmp_path)
    assert commands["commands"]["test"] == ["pnpm", "run", "test"]
    assert commands["commands"]["build"] == ["pnpm", "run", "build"]
    assert commands["runner"] == "pnpm"


def test_comandos_do_makefile_sao_descobertos(tmp_path):
    """Um Makefile sem manifest fornece os comandos de build e teste."""
    (tmp_path / "Makefile").write_text("test:\n\tpytest\nbuild:\n\tmake\nlint:\n\truff\n", encoding="utf-8")
    commands = discover_commands(tmp_path)
    assert commands["commands"]["test"] == ["make", "test"]
    assert commands["commands"]["build"] == ["make", "build"]


def test_manifest_pyproject_e_lido(tmp_path):
    """O manifesto do Python devolve nome, versão e dependências."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "exemplo"\nversion = "1.2.3"\ndependencies = ["httpx", "pydantic"]\n',
        encoding="utf-8",
    )
    manifest = read_manifest(tmp_path / "pyproject.toml")
    assert manifest["name"] == "exemplo"
    assert manifest["version"] == "1.2.3"
    assert "httpx" in manifest["dependencies"]


def test_manifest_quebrado_nao_derruba_a_descoberta(tmp_path):
    """Um manifesto malformado devolve um dicionário vazio, sem exceção."""
    (tmp_path / "package.json").write_text("{isto nao e json", encoding="utf-8")
    manifest = read_manifest(tmp_path / "package.json")
    assert manifest == {"name": "", "version": "", "scripts": {}, "dependencies": []}


def test_git_status_marca_alteracoes(tmp_path):
    """O estado do repositório lista o arquivo alterado e a branch atual."""
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "teste@callidus.local")
    _git(tmp_path, "config", "user.name", "Teste")
    (tmp_path / "a.txt").write_text("conteudo", encoding="utf-8")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-m", "primeiro")
    (tmp_path / "a.txt").write_text("alterado", encoding="utf-8")
    status = git_status(tmp_path)
    assert status["success"] is True
    assert status["count"] == 1
    assert status["changes"][0]["path"] == "a.txt"
    assert status["branch"].startswith("main")


def test_git_log_lista_o_historico(tmp_path):
    """O histórico devolve os commits com hash, autor e mensagem."""
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "teste@callidus.local")
    _git(tmp_path, "config", "user.name", "Teste")
    (tmp_path / "a.txt").write_text("conteudo", encoding="utf-8")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-m", "primeiro")
    log = git_log(tmp_path)
    assert log["count"] == 1
    assert log["commits"][0]["message"] == "primeiro"
    assert git_branch(tmp_path)["current"] == "main"


def test_pasta_que_nao_e_repositorio_devolve_erro(tmp_path):
    """Uma pasta sem repositório devolve erro controlado."""
    assert is_repository(tmp_path) is False
    assert git_status(tmp_path)["success"] is False


def test_resumo_de_teste_distingue_sucesso_e_falha():
    """O resumo separa sucesso confirmado de falha e de resultado inconclusivo."""
    ok = summarize_test_output("2 passed in 0.10s", 0)
    assert ok["status"] == "passed"
    assert ok["counts"]["passed"] == 2
    failed = summarize_test_output("FAILED tests/test_x.py::test_y - AssertionError\n1 failed", 1)
    assert failed["status"] == "failed"
    assert failed["counts"]["failed"] == 1
    unknown = summarize_test_output("saida estranha", 3)
    assert unknown["status"] == "inconclusive"
    assert unknown["inconclusive"] is True


def test_execucao_de_verificacao_relata_codigo_de_saida():
    """A execução de uma verificação devolve o código de saída e o resumo."""
    result = run_check([sys.executable, "-c", "print('ok')"], timeout=30)
    assert result["success"] is True
    assert result["exit_code"] == 0
    assert "ok" in result["output"]


def test_execucao_de_verificacao_reporta_ferramenta_ausente():
    """Uma verificação com executável inexistente diz o que falta."""
    result = run_check(["comando-que-nao-existe-xyz"], timeout=10)
    assert result["success"] is False
    assert result["missing_tool"] == "comando-que-nao-existe-xyz"


@pytest.mark.asyncio
async def test_ferramentas_de_engenharia_sao_declaradas(tmp_path):
    """As ferramentas de engenharia estão registradas com risco e família corretos."""
    from agent.tools.registry import ToolContext, build_default_registry

    reg = build_default_registry()
    spec = reg.get_spec("project_info")
    assert spec.family == "engineering"
    assert spec.risk == "read"
    out = await reg.execute("project_info", ToolContext(project_root=str(tmp_path)), {})
    assert out["success"] is True
    assert "languages" in out["project"]
