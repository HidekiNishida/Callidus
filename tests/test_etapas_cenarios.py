"""
Arquivo: tests/test_etapas_cenarios.py
Nome: test_etapas_cenarios.py
Propósito: verificar, de ponta a ponta pelo orquestrador real, os cenários obrigatórios de confiabilidade (Etapa 1) e decomposição (Etapa 2).
Responsabilidade: camada de testes — integração: orquestrador, executor, portão de verificação, recuperação, retomada, consolidação e resumos.
Componentes: cenário 1 (ferramenta falha), 2 (verificação reprova), 3 (retomada após queda), 4/6 (dependências e arquivo compartilhado), 8 (tarefa simples).
Dependências: agent.orchestrator.runner, agent.services, agent.persistence, agent.orchestrator.subtask_summary, pytest.
Observações: banco e workspace temporários; provedor roteirizado (sem rede); o cenário 7 está em tests/test_granular_approval.py.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.domain.enums import AttemptKind, TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate, TaskDependencyCreate
from agent.orchestrator.consolidation import children_of
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EvidenceModel, OperationAttemptModel, TaskModel
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


class _Scripted:
    """Provedor roteirizado: devolve as respostas na ordem e guarda os prompts recebidos."""

    name = "mock"
    last_usage = None

    def __init__(self, replies: list[str]) -> None:
        """Guarda as respostas programadas."""
        self.replies = replies
        self.prompts: list[str] = []

    async def chat(self, request):
        """Registra o prompt e devolve a próxima resposta (a última se repete)."""
        self.prompts.append("\n".join(m.content for m in request.messages))
        reply = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]

        class _R:
            """Resposta falsa."""

            content = reply
            reasoning = None
            tool_calls = None

        return _R()


def _env(tmp_path: Path):
    """Banco e workspace temporários."""
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    settings = Settings(data_dir=tmp_path / "data")
    factory = build_session_factory(init_db(settings=settings))
    return settings, factory, workspace


def _leaf_under_root(session, workspace: Path, *, metadata: dict, objective: str):
    """Raiz já planejada com uma única etapa folha; devolve (projeto, raiz, etapa, run)."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(workspace)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Objetivo", objective=objective))
    root.status = TaskStatus.PLANNING.value
    leaf = tasks.create_task(
        project.id,
        TaskCreate(title="Alterar calc.py", objective=objective, parent_id=root.id, metadata=metadata),
    )
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True}),
    )
    session.commit()
    return project, root, leaf, run


def _evidences(session, task_id) -> list[EvidenceModel]:
    """Evidências da etapa, da mais antiga para a mais nova."""
    return list(
        session.scalars(
            select(EvidenceModel).where(EvidenceModel.task_id == task_id).order_by(EvidenceModel.created_at)
        ).all()
    )


@pytest.mark.asyncio
async def test_cenario1_falha_de_ferramenta_e_recuperada_sem_conclusao_falsa(tmp_path: Path, monkeypatch):
    """Cenário 1: a ferramenta de escrita falha na primeira chamada. A falha é diagnosticada e
    persistida, a etapa volta para nova tentativa controlada, e só conclui com evidência aprovada."""
    settings, factory, workspace = _env(tmp_path)
    (workspace / "calc.py").write_text("def soma(a, b):\n    return a - b\n", encoding="utf-8")
    session = factory()
    _, root, leaf, run = _leaf_under_root(
        session,
        workspace,
        objective="Corrija soma em calc.py",
        metadata={
            "model_operation": True,
            "atomic": True,
            "verification": {"type": "file_contains", "path": "calc.py", "contains": "return a + b"},
        },
    )
    provider = _Scripted(['{"path": "calc.py", "old_string": "return a - b", "new_string": "return a + b"}'])
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: provider)

    from agent.tools.registry import ToolRegistry

    real = ToolRegistry.execute
    calls = {"n": 0}

    async def flaky(self, tool_id, ctx, args, *, approved=False):
        """Primeira escrita falha como falha de ferramenta (disco indisponível)."""
        if tool_id in {"edit_file", "write_file"}:
            calls["n"] += 1
            if calls["n"] == 1:
                return {"success": False, "error": "disco indisponível"}
        return await real(self, tool_id, ctx, args, approved=approved)

    monkeypatch.setattr(ToolRegistry, "execute", flaky)

    log = await RunOrchestrator(session, settings).run_until_idle(run.id, max_steps=12)
    session.commit()

    task = session.get(TaskModel, leaf.id)
    assert task.status == TaskStatus.COMPLETED.value, log
    failures = task.metadata_json.get("failures") or []
    assert any("disco indisponível" in str(f.get("detail")) for f in failures), "diagnóstico persistido"
    assert calls["n"] == 2, "uma nova tentativa controlada, não um laço"
    evs = _evidences(session, leaf.id)
    assert evs and evs[-1].passed is True
    assert (workspace / "calc.py").read_text(encoding="utf-8").endswith("return a + b\n")
    # Nenhuma conclusão antes da evidência: a única evidência aprovada é a última.
    assert [e.passed for e in evs].count(True) == 1


@pytest.mark.asyncio
async def test_cenario2_verificacao_reprova_recupera_e_reverifica(tmp_path: Path, monkeypatch):
    """Cenário 2: a primeira implementação é incorreta. O portão reprova, identifica o critério
    não satisfeito, desfaz a escrita reprovada, passa a orientação à próxima tentativa e só
    conclui depois da aprovação."""
    settings, factory, workspace = _env(tmp_path)
    original = "def soma(a, b):\n    return 0\n"
    (workspace / "calc.py").write_text(original, encoding="utf-8")
    session = factory()
    _, root, leaf, run = _leaf_under_root(
        session,
        workspace,
        objective="Implemente soma em calc.py",
        metadata={
            "model_operation": True,
            "atomic": True,
            "verification": {"type": "file_contains", "path": "calc.py", "contains": "return a + b"},
        },
    )
    provider = _Scripted(
        [
            '{"path": "calc.py", "content": "def soma(a, b):\\n    return a * b\\n"}',
            '{"path": "calc.py", "content": "def soma(a, b):\\n    return a + b\\n"}',
        ]
    )
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: provider)

    states: list[str] = []
    orch = RunOrchestrator(session, settings)
    for _ in range(12):
        out = await orch.step(run.id)
        states.append(out.get("action"))
        if session.get(TaskModel, leaf.id).status == TaskStatus.COMPLETED.value:
            break
        if out.get("action") == "verify_failed":
            # Logo após a reprovação: o disco voltou ao original e a etapa não concluiu.
            assert (workspace / "calc.py").read_text(encoding="utf-8") == original
            assert session.get(TaskModel, leaf.id).status == TaskStatus.RETRY_PENDING.value
    session.commit()

    task = session.get(TaskModel, leaf.id)
    assert "verify_failed" in states and task.status == TaskStatus.COMPLETED.value, states
    recovery = task.metadata_json["verification_recovery"]
    assert recovery["unmet_criterion"].startswith("file_contains calc.py")
    assert recovery["diagnosis"]["cause"]
    assert len(provider.prompts) == 2
    assert "return a + b" in provider.prompts[1], "a orientação da recuperação chega à nova tentativa"
    evs = _evidences(session, leaf.id)
    assert [e.passed for e in evs] == [False, True]
    assert (workspace / "calc.py").read_text(encoding="utf-8").endswith("return a + b\n")


@pytest.mark.asyncio
async def test_cenario3_retomada_apos_queda_nao_repete_o_que_concluiu(tmp_path: Path):
    """Cenário 3: o processo cai depois de uma subtarefa concluída e antes da conclusão global.
    O estado é reconstruído do SQLite, o que concluiu é preservado e a execução retoma do ponto certo."""
    fixture = Path(__file__).parent / "fixtures" / "sample_project"
    settings, factory, _ = _env(tmp_path)
    workspace = tmp_path / "proj"
    shutil.copytree(fixture, workspace)
    session = factory()
    project = ProjectService(session).create_project(ProjectCreate(name="e2e", root_path=str(workspace)))
    root = TaskService(session).create_task(project.id, TaskCreate(title="Obj", objective="e2e corrigir calc.py"))
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True}),
    )
    session.commit()

    orch = RunOrchestrator(session, settings)
    done = None
    for _ in range(40):
        await orch.step(run.id)
        session.commit()
        kids = children_of(session, root.id)
        done = next((k for k in kids if k.status == TaskStatus.COMPLETED.value), None)
        if done is not None:
            break
    assert done is not None and session.get(TaskModel, root.id).status != TaskStatus.COMPLETED.value
    done_id = done.id

    def executions(sess) -> int:
        """Tentativas de execução (modelo/ferramenta) da subtarefa concluída — verificações não contam."""
        rows = sess.scalars(select(OperationAttemptModel).where(OperationAttemptModel.task_id == done_id)).all()
        return len([a for a in rows if a.kind != AttemptKind.VERIFICATION.value])

    before = executions(session)
    session.close()  # queda: nada em memória sobrevive

    restarted = factory()
    log = await RunOrchestrator(restarted, settings).run_until_idle(run.id, max_steps=80)
    restarted.commit()
    assert restarted.get(TaskModel, root.id).status == TaskStatus.COMPLETED.value, log[-3:]
    assert any(x.get("action") == "run_completed" for x in log)
    assert executions(restarted) == before, "a subtarefa concluída não foi reexecutada na retomada"


def _tool_step(title: str, path: str, content: str, *, contains: str) -> TaskCreate:
    """Etapa determinística: grava o arquivo e verifica um trecho."""
    return TaskCreate(
        title=title,
        objective=title,
        metadata={
            "tool": "write_file",
            "tool_args": {"path": path, "content": content},
            "verification": {"type": "file_contains", "path": path, "contains": contains},
        },
    )


@pytest.mark.asyncio
async def test_cenario4_e_6_dependencias_resumos_e_arquivo_compartilhado(tmp_path: Path):
    """Cenários 4 e 6: dependências são respeitadas (B só roda depois de A), o pai consolida com
    resumos estruturados, o arquivo alterado pelas duas etapas aparece como compartilhado e a
    evidência de A, desatualizada pela escrita de B, é **reverificada** — sem reexecutar A e sem
    sobrescrever silenciosamente o trabalho de B."""
    settings, factory, workspace = _env(tmp_path)
    session = factory()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(workspace)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Objetivo", objective="Montar mod.py em duas partes"))
    root.status = TaskStatus.PLANNING.value
    step_b = tasks.create_task(
        project.id,
        TaskCreate(
            **{
                **_tool_step("Parte B", "mod.py", "def a():\n    return 1\n\n\ndef b():\n    return 2\n", contains="def b").model_dump(),
                "parent_id": root.id,
            }
        ),
    )
    step_a = tasks.create_task(
        project.id,
        TaskCreate(**{**_tool_step("Parte A", "mod.py", "def a():\n    return 1\n", contains="def a").model_dump(), "parent_id": root.id}),
    )
    tasks.add_dependency(step_b.id, TaskDependencyCreate(depends_on_task_id=step_a.id))
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True}),
    )
    session.commit()

    orch = RunOrchestrator(session, settings)
    order: list[str] = []
    for _ in range(30):
        out = await orch.step(run.id)
        if out.get("action") in {"verified_ok"} and out.get("task_id"):
            order.append(out["task_id"])
        if session.get(TaskModel, root.id).status == TaskStatus.COMPLETED.value:
            break
    session.commit()

    assert order.index(str(step_a.id)) < order.index(str(step_b.id)), "B depende de A"
    writes_a = [
        a
        for a in session.scalars(select(OperationAttemptModel).where(OperationAttemptModel.task_id == step_a.id)).all()
        if a.kind == AttemptKind.TOOL.value
    ]
    assert len(writes_a) == 1, "A não foi reexecutada: só reverificada"
    assert "def b" in (workspace / "mod.py").read_text(encoding="utf-8"), "o trabalho de B não foi sobrescrito"
    report = session.get(TaskModel, root.id).consolidated_result_json
    assert report["achieved"] is True
    shared = report["shared_files"]
    assert shared and shared[0]["path"] == "mod.py" and set(shared[0]["tasks"]) == {str(step_a.id), str(step_b.id)}
    summaries = {c["title"]: c["summary"] for c in report["children"]}
    assert summaries["Parte B"]["files_changed"] == ["mod.py"]
    assert summaries["Parte A"]["evidences"][-1]["passed"] is True
    assert {"objective", "findings", "files_analyzed", "decisions", "tests_run", "problems", "pending", "risks", "next_actions"} <= set(
        summaries["Parte A"]
    )


@pytest.mark.asyncio
async def test_cenario8_tarefa_simples_executa_direto(tmp_path: Path, monkeypatch):
    """Cenário 8: "leia um arquivo e explique" não cria árvore de alteração: lê o arquivo (com
    verificação proporcional) e responde, sem nenhuma escrita."""
    settings, factory, workspace = _env(tmp_path)
    (workspace / "README.md").write_text("# Calc\nSoma dois números.\n", encoding="utf-8")
    session = factory()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(workspace)))
    root = TaskService(session).create_task(
        project.id, TaskCreate(title="Explicar", objective="Leia o arquivo README.md e explique seu conteúdo")
    )
    run = RunService(session).start_run(
        project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock"})
    )
    session.commit()
    provider = _Scripted(["O README descreve uma calculadora que soma dois números."])
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: provider)

    log = await RunOrchestrator(session, settings).run_until_idle(run.id, max_steps=25)
    session.commit()

    plan = next(x for x in log if x.get("action") == "decomposed")
    assert plan["source"] == "direct-read" and plan["count"] == 2
    kids = children_of(session, root.id)
    assert sorted(k.title for k in kids) == ["Ler README.md", "Responder"]
    writes = [
        a
        for a in session.scalars(select(OperationAttemptModel)).all()
        if a.kind == AttemptKind.TOOL.value and a.provider in {"write_file", "edit_file", "delete_file", "move_file"}
    ]
    assert writes == []
    read = next(k for k in kids if k.title == "Ler README.md")
    assert _evidences(session, read.id)[-1].passed is True
    assert (workspace / "README.md").read_text(encoding="utf-8").startswith("# Calc")
    assert any("calculadora" in p or "Calc" in p for p in provider.prompts)


@pytest.mark.asyncio
async def test_pai_com_criterio_proprio_nao_conclui_so_porque_os_filhos_concluiram(tmp_path: Path):
    """5.8: filhos aprovados não bastam quando o pai declara o próprio critério — o pai passa
    pelo mesmo portão e, reprovado, não conclui."""
    from agent.orchestrator.consolidation import consolidate_parent

    settings, factory, workspace = _env(tmp_path)
    session = factory()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(workspace)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Objetivo", objective="Montar mod.py"))
    parent = tasks.create_task(
        project.id,
        TaskCreate(
            title="Módulo",
            objective="mod.py com a e c",
            parent_id=root.id,
            metadata={"verification": {"type": "file_contains", "path": "mod.py", "contains": "def c"}},
        ),
    )
    parent.status = TaskStatus.PLANNING.value
    child = tasks.create_task(
        project.id,
        TaskCreate(**{**_tool_step("Parte A", "mod.py", "def a():\n    return 1\n", contains="def a").model_dump(), "parent_id": parent.id}),
    )
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True}),
    )
    session.commit()
    orch = RunOrchestrator(session, settings)
    for _ in range(12):
        await orch.step(run.id)
        if session.get(TaskModel, child.id).status == TaskStatus.COMPLETED.value:
            break
    consolidate_parent(session, parent.id)
    assert session.get(TaskModel, parent.id).status == TaskStatus.VERIFYING.value
    out = await orch.step(run.id)
    assert out["action"] in {"verify_failed", "verify_blocked"}
    assert session.get(TaskModel, parent.id).status != TaskStatus.COMPLETED.value


def test_rota_de_resumo_estruturado(tmp_path: Path):
    """GET /tasks/{id}/summary devolve o resumo estruturado; 404 para tarefa inexistente."""
    import uuid

    from fastapi.testclient import TestClient

    from agent.api import deps
    from agent.api.main import app

    settings, factory, workspace = _env(tmp_path)
    session = factory()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(workspace)))
    task = TaskService(session).create_task(project.id, TaskCreate(title="T", objective="ler"))
    session.commit()

    def _db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[deps.db_session] = _db
    try:
        client = TestClient(app)
        body = client.get(f"/tasks/{task.id}/summary").json()
        assert body["task_id"] == str(task.id) and body["files_changed"] == [] and body["pending"]
        assert client.get(f"/tasks/{uuid.uuid4()}/summary").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_validador_da_resposta_final_nao_reprova_codigo_nem_por_exemplo():
    """Falsos negativos achados na avaliação real: f-string em bloco de código e "por exemplo"
    reprovavam a resposta; espaço reservado de verdade continua reprovado."""
    from agent.orchestrator.closing import validate_final_answer

    assert validate_final_answer("Use, por exemplo, `soma(1, 2)`.")[0] is True
    assert validate_final_answer("Código:\n```python\nprint(f'{nome}')\n```\nPronto.")[0] is True
    assert validate_final_answer("O total é {total_vendas}.")[0] is False
    assert validate_final_answer("Contato: [exemplo de e-mail]")[0] is False
    assert validate_final_answer("")[0] is False


@pytest.mark.asyncio
async def test_resposta_final_invalida_vira_nova_tentativa_sem_derrubar_o_run(tmp_path: Path, monkeypatch):
    """Regressão da avaliação real: o caminho "resposta final inválida" levantava AttributeError
    e o passo escondia o erro atrás de UnboundLocalError. Agora vira falha registrada e nova tentativa."""
    settings, factory, workspace = _env(tmp_path)
    (workspace / "README.md").write_text("# Calc\n", encoding="utf-8")
    session = factory()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(workspace)))
    root = TaskService(session).create_task(
        project.id, TaskCreate(title="Explicar", objective="Leia o arquivo README.md e explique seu conteúdo")
    )
    run = RunService(session).start_run(project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock"}))
    session.commit()
    provider = _Scripted(["O total é {total_vendas}.", "O README apresenta a calculadora."])
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: provider)

    log = await RunOrchestrator(session, settings).run_until_idle(run.id, max_steps=25)
    actions = [x.get("action") for x in log]
    assert "final_answer_invalid" in actions and "run_completed" in actions, actions
    answer = next(k for k in children_of(session, root.id) if k.title == "Responder")
    assert any("template" in str(f.get("detail")) for f in answer.metadata_json.get("failures") or [])


@pytest.mark.asyncio
async def test_erro_no_passo_sobe_intacto(tmp_path: Path, monkeypatch):
    """Uma exceção no corpo do passo chega a quem chamou como ela é (não como UnboundLocalError)."""
    settings, factory, workspace = _env(tmp_path)
    session = factory()
    _, root, leaf, run = _leaf_under_root(session, workspace, objective="x", metadata={"model_operation": True})

    async def boom(self, run_id):
        raise RuntimeError("falha original")

    monkeypatch.setattr(RunOrchestrator, "_step_body", boom)
    with pytest.raises(RuntimeError, match="falha original"):
        await RunOrchestrator(session, settings).step(run.id)


def test_descoberta_do_ambiente_em_ferramenta_de_inspecao():
    """`git_status` fora de repositório é a resposta da inspeção; falha de verdade não é."""
    from agent.orchestrator.execution.tool_results import environment_finding

    out = {"success": False, "stderr": "fatal: not a git repository (or any of the parent directories): .git\n"}
    assert environment_finding("git_status", out) == "a pasta do projeto não é um repositório git"
    assert environment_finding("run_command", out) is None
    assert environment_finding("git_status", {"success": False, "stderr": "fatal: bad object"}) is None
    assert environment_finding("git_status", {"success": True}) is None


@pytest.mark.asyncio
async def test_plano_com_git_status_fora_de_repositorio_segue_sem_repetir(tmp_path: Path):
    """Regressão da avaliação real: a etapa `git_status` numa pasta sem git conclui com a
    descoberta na primeira chamada; o plano segue sem estagnação nem replanejamento."""
    import subprocess

    settings, factory, workspace = _env(tmp_path)
    inside = subprocess.run(["git", "rev-parse"], cwd=workspace, capture_output=True).returncode == 0
    if inside:
        pytest.skip("a pasta temporária está dentro de um repositório git")
    (workspace / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    session = factory()
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(workspace)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Objetivo", objective="Inspecionar o projeto"))
    root.status = TaskStatus.PLANNING.value
    git = tasks.create_task(
        project.id,
        TaskCreate(title="Verificar status do repositório", objective="git status", parent_id=root.id,
                   metadata={"tool": "git_status", "tool_args": {}}),
    )
    read = tasks.create_task(
        project.id,
        TaskCreate(title="Ler calc.py", objective="ler", parent_id=root.id,
                   metadata={"tool": "read_file", "tool_args": {"path": "calc.py"},
                             "verification": {"type": "file_exists", "path": "calc.py"}}),
    )
    tasks.add_dependency(read.id, TaskDependencyCreate(depends_on_task_id=git.id))
    run = RunService(session).start_run(
        project.id, ExecutionRunCreate(root_task_id=root.id, config={"provider": "mock", "approve_risky_tools": True})
    )
    session.commit()

    log = await RunOrchestrator(session, settings).run_until_idle(run.id, max_steps=12)
    actions = [x.get("action") for x in log]
    assert "stagnation_replan" not in actions and "replanned" not in actions, actions
    git_task = session.get(TaskModel, git.id)
    assert git_task.status == TaskStatus.COMPLETED.value
    assert git_task.metadata_json["environment_finding"] == "a pasta do projeto não é um repositório git"
    calls = [a for a in session.scalars(select(OperationAttemptModel).where(OperationAttemptModel.task_id == git.id)).all()
             if a.kind == AttemptKind.TOOL.value]
    assert len(calls) == 1, "a mesma resposta do ambiente não é repetida"
    assert session.get(TaskModel, read.id).status == TaskStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_etapa_que_roda_os_testes_e_passa_grava_evidencia(tmp_path: Path):
    """Regressão da avaliação real (qwen3-vl:8b): `run_pytest` verde concluía "sem verificador",
    o requisito ficava sem prova e era reaberto. Agora a etapa grava a evidência do pytest."""
    settings, factory, workspace = _env(tmp_path)
    (workspace / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (workspace / "test_calc.py").write_text("import calc\n\n\ndef test_add():\n    assert calc.add(2, 3) == 5\n", encoding="utf-8")
    session = factory()
    _, root, leaf, run = _leaf_under_root(
        session, workspace, objective="Rodar os testes", metadata={"tool": "run_pytest", "tool_args": {}}
    )
    await RunOrchestrator(session, settings).run_until_idle(run.id, max_steps=6)
    task = session.get(TaskModel, leaf.id)
    assert task.status == TaskStatus.COMPLETED.value
    evs = _evidences(session, leaf.id)
    assert evs and evs[-1].verifier == "pytest" and evs[-1].passed is True
    assert task.metadata_json["implicit_verification"]["type"] == "pytest"


@pytest.mark.asyncio
async def test_escrita_que_apaga_o_arquivo_e_reprovada_e_desfeita(tmp_path: Path, monkeypatch):
    """Regressão da avaliação real (qwen3-vl:8b, arquivo_grande): `write_file` trocou um arquivo de
    362 linhas pelo trecho corrigido e a verificação implícita aprovou. Agora a escrita destrutiva
    reprova, o arquivo é restaurado, a orientação pede edit_file e a nova tentativa preserva o resto."""
    settings, factory, workspace = _env(tmp_path)
    funcs = "".join(f"def f{i}(x):\n    return x + {i}\n\n\n" for i in range(30))
    original = "def add(a, b):\n    return a * b\n\n\n" + funcs
    (workspace / "calc.py").write_text(original, encoding="utf-8")
    session = factory()
    _, root, leaf, run = _leaf_under_root(
        session, workspace, objective="Corrija add em calc.py", metadata={"model_operation": True, "atomic": True}
    )
    provider = _Scripted(
        [
            '{"path": "calc.py", "content": "def add(a, b):\\n    return a + b\\n"}',
            '{"path": "calc.py", "old_string": "return a * b", "new_string": "return a + b"}',
        ]
    )
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: provider)

    await RunOrchestrator(session, settings).run_until_idle(run.id, max_steps=12)
    task = session.get(TaskModel, leaf.id)
    evs = _evidences(session, leaf.id)
    assert evs[0].passed is False and evs[0].detail_json.get("destructive_write") is True
    assert "edit_file" in provider.prompts[1]
    assert task.status == TaskStatus.COMPLETED.value
    text = (workspace / "calc.py").read_text(encoding="utf-8")
    assert "return a + b" in text and "def f29" in text, "o resto do arquivo foi preservado"


def test_criterio_implicito_so_protege_arquivo_existente_e_grande():
    """O volume só é exigido para arquivo que já existia com tamanho relevante."""
    from agent.orchestrator.execution.writes import implicit_spec

    assert "preserve_lines" not in implicit_spec("a.py", "x = 1", lines_before=None)
    assert "preserve_lines" not in implicit_spec("a.py", "x = 1", lines_before=5)
    assert implicit_spec("a.py", "x = 1", lines_before=120)["preserve_lines"] == 120



@pytest.mark.asyncio
async def test_reescrita_inteira_de_arquivo_grande_e_recusada(tmp_path: Path):
    """Regressão da avaliação real: reescrever de memória um arquivo grande alterava funções que
    não deviam mudar. A ferramenta recusa sem tocar o disco; arquivo novo ou pequeno continua livre."""
    from agent.domain.failures import FailureCause, classify_tool_result
    from agent.tools.builtins import LARGE_REWRITE_LINES
    from agent.tools.registry import ToolContext, build_default_registry

    big = "".join(f"x{i} = {i}\n" for i in range(LARGE_REWRITE_LINES))
    (tmp_path / "big.py").write_text(big, encoding="utf-8")
    (tmp_path / "small.py").write_text("a = 1\n", encoding="utf-8")
    registry = build_default_registry()
    ctx = ToolContext(project_root=str(tmp_path))

    refused = await registry.execute("write_file", ctx, {"path": "big.py", "content": "x0 = 0\n"})
    assert refused["success"] is False and "edit_file" in refused["error"]
    assert (tmp_path / "big.py").read_text(encoding="utf-8") == big
    assert classify_tool_result(refused).cause == FailureCause.TOOL_INPUT
    assert (await registry.execute("write_file", ctx, {"path": "small.py", "content": "a = 2\n"}))["success"]
    assert (await registry.execute("write_file", ctx, {"path": "novo.py", "content": big + big}))["success"]
    assert (await registry.execute("edit_file", ctx, {"path": "big.py", "old_string": "x1 = 1", "new_string": "x1 = 11"}))["success"]


class _TestRunner:
    """Modelo com ciclo de ferramentas: roda a suíte e responde em texto, sem escrita."""

    name = "ollama"
    last_usage = None

    def __init__(self) -> None:
        """Zera o contador de chamadas."""
        self.calls = 0

    def capabilities(self):
        """Declara ferramentas e ciclo de ferramentas."""
        from agent.providers.base import ProviderCapabilities

        return ProviderCapabilities(tools=True, tool_loop=True)

    async def chat(self, request):
        """Primeiro pede `run_pytest`; depois relata o resultado em texto."""
        from agent.providers.base import ToolCall

        self.calls += 1
        calls = [ToolCall(id="t1", name="run_pytest", arguments={})] if self.calls == 1 else []
        content = "" if self.calls == 1 else "Os testes passaram."
        return type(
            "R",
            (),
            {"content": content, "tool_calls": calls, "reasoning": None,
             "completion_tokens_estimate": 10, "prompt_tokens_estimate": 30},
        )()


@pytest.mark.asyncio
async def test_etapa_de_executar_testes_entrega_o_veredito_e_nao_saida_invalida(tmp_path: Path, monkeypatch):
    """Regressão da avaliação real (gpt-oss:20b, arquivo_grande): "executar testes" como operação
    de modelo rodava a suíte, respondia em texto e era recusada como saída inválida até a pausa.
    Agora a entrega é o veredito dos testes, medido de novo pelo portão."""
    settings, factory, workspace = _env(tmp_path)
    (workspace / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (workspace / "test_calc.py").write_text("import calc\n\n\ndef test_add():\n    assert calc.add(2, 3) == 5\n", encoding="utf-8")
    session = factory()
    _, root, leaf, run = _leaf_under_root(
        session, workspace, objective="Executar os testes unitários", metadata={"model_operation": True}
    )
    provider = _TestRunner()
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: provider)

    log = await RunOrchestrator(session, settings).run_until_idle(run.id, max_steps=6)
    actions = [x.get("action") for x in log]
    assert "model_operation_invalid" not in actions, actions
    task = session.get(TaskModel, leaf.id)
    assert task.status == TaskStatus.COMPLETED.value
    evs = _evidences(session, leaf.id)
    assert evs[-1].verifier == "pytest" and evs[-1].passed is True
    assert task.consolidated_result_json["tests_run"] is True


@pytest.mark.asyncio
async def test_etapa_de_testes_que_reprovam_segue_a_recuperacao(tmp_path: Path, monkeypatch):
    """Se a suíte reprova, a etapa não conclui: o portão reprova e a recuperação assume."""
    settings, factory, workspace = _env(tmp_path)
    (workspace / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (workspace / "test_calc.py").write_text("import calc\n\n\ndef test_add():\n    assert calc.add(2, 3) == 5\n", encoding="utf-8")
    session = factory()
    _, root, leaf, run = _leaf_under_root(
        session, workspace, objective="Executar os testes unitários", metadata={"model_operation": True}
    )
    monkeypatch.setattr("agent.orchestrator.runner._select_provider", lambda settings, config: _TestRunner())

    orch = RunOrchestrator(session, settings)
    out = None
    for _ in range(4):
        out = await orch.step(run.id)
        if out.get("action") in {"verify_failed", "verify_blocked", "blocked_loop"}:
            break
    assert out["action"] in {"verify_failed", "verify_blocked"}, out
    assert session.get(TaskModel, leaf.id).status != TaskStatus.COMPLETED.value
    assert _evidences(session, leaf.id)[-1].passed is False
