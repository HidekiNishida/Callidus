"""
Arquivo: tests/test_real_workflow_integration.py
Nome: test_real_workflow_integration.py
Propósito: demonstrar, com execução real, os fluxos de abrir aplicativo, manter software e usar skill.
Responsabilidade: camada de testes — integração do agente com o sistema, o projeto e o ciclo de vida das skills.
Componentes: abertura de aplicativo de demonstração, tarefa de desenvolvimento com testes, criação e uso de skill.
Dependências: agent.tools, agent.system, agent.engineering, agent.skills.authoring, pytest.
Observações: sem mocks — o teste abre um processo real, roda a suíte real e cria uma skill de verdade.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agent.skills.authoring import SkillAuthoringService, SkillStore
from agent.skills.discovery import SkillRegistry
from agent.tools.registry import ToolContext, build_default_registry

REPO = Path(__file__).resolve().parents[1]
DEMO_APP = REPO / "lab" / "demo_app.py"


def _ctx(root: Path) -> ToolContext:
    """Contexto de ferramenta apontado para uma pasta temporária.

    Args:
        root: pasta do workspace.

    Returns:
        O contexto pronto para uso.
    """
    return ToolContext(project_root=str(root))


@pytest.mark.asyncio
async def test_fluxo_de_aplicativo_abre_verifica_e_inspeciona(tmp_path):
    """O agente abre o aplicativo de demonstração, confere o processo e inspeciona o resultado.

    A sequência é a mesma que o agente executa: abrir, listar o processo, inspecionar o
    processo e ler o sinal de vida que o aplicativo gravou.
    """
    reg = build_default_registry()
    ctx = _ctx(tmp_path)
    heartbeat = tmp_path / "app" / "sinal.json"

    launched = await reg.execute(
        "launch_app",
        ctx,
        {
            "name": sys.executable,
            "args": [str(DEMO_APP), "--out", str(heartbeat), "--seconds", "20"],
            "background": True,
        },
        approved=True,
    )
    assert launched["success"] is True, launched
    handle = launched["handle"]
    try:
        # 1. O processo aparece na lista do sistema.
        found = await reg.execute("list_processes", ctx, {"match": "demo_app.py", "limit": 50})
        assert found["success"] is True
        assert any(item["pid"] == handle["pid"] for item in found["processes"])

        # 2. A inspeção do processo devolve o comando realmente executado.
        info = await reg.execute("process_info", ctx, {"pid": handle["pid"]})
        assert info["success"] is True
        assert "demo_app.py" in info["process"]["command"]

        # 3. O resultado observável do aplicativo é lido do disco.
        deadline = time.monotonic() + 15
        payload = {}
        while time.monotonic() < deadline:
            if heartbeat.is_file():
                try:
                    payload = json.loads(heartbeat.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    payload = {}
                if payload:
                    break
            time.sleep(0.2)
        assert payload, "o aplicativo não gravou o sinal de vida"
        assert payload["pid"] == handle["pid"]
        assert payload["port"] > 0

        # 4. O processo responde de verdade: a rota de estado devolve 200.
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{payload['port']}/", timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
        assert body["status"] == "ok"
    finally:
        await reg.execute("task_cancel", ctx, {"handle_id": handle["handle_id"]}, approved=True)


@pytest.mark.asyncio
async def test_fluxo_de_engenharia_descobre_executa_e_reporta(tmp_path):
    """O agente descobre o projeto, roda os testes e reporta o resultado real de uma correção.

    O projeto de demonstração começa com um teste que falha; a correção é aplicada e a
    suíte passa. O relatório final vem da execução real, não de uma simulação.
    """
    project = tmp_path / "projeto"
    (project / "tests").mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (project / "calculo.py").write_text("def soma(a, b):\n    return a - b\n", encoding="utf-8")
    (project / "conftest.py").write_text("", encoding="utf-8")
    (project / "tests" / "test_calculo.py").write_text(
        "from calculo import soma\n\n\ndef test_soma():\n    assert soma(2, 3) == 5\n", encoding="utf-8"
    )
    reg = build_default_registry()
    ctx = _ctx(project)

    info = await reg.execute("project_info", ctx, {})
    assert info["success"] is True
    assert "python" in info["project"]["languages"]

    commands = await reg.execute("project_commands", ctx, {})
    assert commands["commands"]["test"] == ["python", "-m", "pytest"]

    # 1. A verificação real falha e o relatório diz onde.
    failed = await reg.execute(
        "run_check",
        ctx,
        {"command": [sys.executable, "-m", "pytest", "-q"], "cwd": str(project)},
        approved=True,
    )
    assert failed["success"] is False
    assert failed["status"] == "failed"
    assert failed["counts"]["failed"] == 1

    # 2. A correção é aplicada pela ferramenta de escrita e a verificação real passa.
    written = await reg.execute(
        "write_file",
        ctx,
        {"path": "calculo.py", "content": "def soma(a, b):\n    return a + b\n"},
    )
    assert written["success"] is True
    passed = await reg.execute(
        "run_check",
        ctx,
        {"command": [sys.executable, "-m", "pytest", "-q"], "cwd": str(project)},
        approved=True,
    )
    assert passed["success"] is True, passed["output"]
    assert passed["status"] == "passed"
    assert passed["counts"]["passed"] == 1


@pytest.mark.asyncio
async def test_fluxo_de_skill_cria_valida_testa_e_usa(tmp_path):
    """O agente cria uma skill, valida, testa, ativa e a usa na tarefa seguinte.

    A skill criada é real: fica no disco, tem contrato, tem teste próprio e passa a ser
    reconhecida pelo registro — inclusive pelo seletor, que a escolhe para um objetivo
    compatível.
    """
    store = SkillStore(tmp_path / "skills")
    service = SkillAuthoringService(store)
    created = service.create_draft(
        "revisar-diff",
        "Revisa um diff antes de commitá-lo, procurando mudança de contrato e teste ausente",
        activation=["Quando o pedido é revisar um diff antes de commitá-lo"],
        procedures=[
            "Rode git diff e leia as linhas alteradas",
            "Procure mudança de contrato sem teste correspondente",
            "Relate cada achado com arquivo e linha",
        ],
        validation=["Cada achado tem arquivo e linha", "Nenhum achado sem evidência no diff"],
        risks=["Não altere o código durante a revisão"],
    )
    assert created["success"] is True

    validation = service.validate("revisar-diff")
    assert validation["valid"] is True, validation["errors"]

    # O teste da skill é real: ele verifica o próprio contrato criado.
    tests = store.path_of("revisar-diff") / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    (tests / "test_skill.py").write_text(
        "from pathlib import Path\n\n"
        "SKILL = Path(__file__).resolve().parents[1] / 'SKILL.md'\n\n\n"
        "def test_contrato_tem_criterios():\n"
        "    texto = SKILL.read_text(encoding='utf-8')\n"
        "    assert 'Critérios de ativação' in texto\n"
        "    assert 'Critérios de validação' in texto\n",
        encoding="utf-8",
    )
    tested = service.test("revisar-diff")
    assert tested["status"] == "passed", tested.get("output")

    activated = store.activate("revisar-diff")
    assert activated["success"] is True
    assert store.get("revisar-diff").state == "approved"

    # A skill passa a ser reconhecida pelo registro e escolhida para o objetivo compatível.
    project = tmp_path / "projeto"
    (project / "skills" / "revisar-diff").mkdir(parents=True)
    (project / "skills" / "revisar-diff" / "SKILL.md").write_text(
        (store.path_of("revisar-diff") / "SKILL.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    registry = SkillRegistry(project_root=project)
    assert registry.get("revisar-diff") is not None

    from agent.skills.selector import SkillSelector

    selector = SkillSelector(registry)
    matches = selector.select("revisar o diff antes de commitá-lo")
    assert any(item.skill_id == "revisar-diff" for item in matches)


@pytest.mark.asyncio
async def test_fluxo_de_skill_nao_ativa_sem_validacao(tmp_path):
    """Uma skill com contrato quebrado não é ativada, e o erro traz a validação."""
    store = SkillStore(tmp_path / "skills")
    service = SkillAuthoringService(store)
    service.create_draft("skill-quebrada", "Faz algo")
    manifest = store.read_manifest("skill-quebrada")
    manifest["scripts"] = ["scripts/inexistente.py"]
    store._write_manifest("skill-quebrada", manifest)  # noqa: SLF001 - teste do próprio pacote
    out = store.activate("skill-quebrada")
    assert out["success"] is False
    assert out["validation"]["valid"] is False
    assert any("inexistente.py" in item for item in out["validation"]["errors"])


@pytest.mark.asyncio
async def test_fluxo_de_skill_proposta_registra_evidencia(tmp_path):
    """Uma melhoria proposta a partir de uma execução fica registrada, com a evidência."""
    store = SkillStore(tmp_path / "skills")
    service = SkillAuthoringService(store)
    service.create_draft("skill-base", "Faz algo", procedures=["Passo"])
    proposal = service.propose(
        "skill-base",
        "Incluir a checagem de permissões",
        "Em duas execuções a skill executou um comando que dependia de permissão elevada",
        changes="Adicionar um passo de verificação de permissões",
        evidence=["run-2026-01-01", "run-2026-01-02"],
    )
    assert proposal["success"] is True
    listed = service.list_proposals(skill="skill-base")
    assert len(listed) == 1
    assert listed[0]["evidence"] == ["run-2026-01-01", "run-2026-01-02"]
    resolved = service.resolve_proposal(listed[0]["id"], accept=False, note="precisa de mais casos")
    assert resolved["proposal"]["state"] == "rejected"
    assert resolved["proposal"]["note"] == "precisa de mais casos"


def test_processo_do_agente_continua_um_porvez():
    """A regra de uma inferência por vez continua valendo após a mudança."""
    from agent.config import Settings

    assert Settings().max_concurrent_inferences == 1
    assert os.environ.get("CALLIDUS_MAX_CONCURRENT_INFERENCES") in (None, "", "1")
