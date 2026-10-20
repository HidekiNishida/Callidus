# tests/test_plan_contract.py — o plano do modelo não pode ser descartado por um rótulo fora do contrato
"""Regressões do contrato do plano.

O modelo rotula as etapas do jeito que entende. Um rótulo fora do enum (`kind: "final_answer"`)
descartava o plano inteiro e o orquestrador caía no template genérico — perdendo a
especificidade do objetivo, a cobertura de requisitos e as dependências que o modelo tinha
acertado. Aqui o plano é normalizado e os desvios ficam registrados.
"""
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import TaskKind, TaskStatus
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.orchestrator.decomposition import DecompositionResult, SubTaskSpec
from agent.orchestrator.plan_contract import (
    normalize_covers,
    normalize_depends,
    normalize_kind,
    normalize_plan_payload,
)
from agent.orchestrator.plan_validation import validate_and_repair, validate_children
from agent.persistence.database import build_session_factory, init_db
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path):
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


def test_kind_final_answer_e_aceito_como_etapa_de_resposta():
    kind, warning = normalize_kind("final_answer")

    assert kind == TaskKind.OPERATION
    assert warning is None


def test_kind_desconhecido_vira_operacao_com_aviso():
    kind, warning = normalize_kind("coisa_qualquer")

    assert kind == TaskKind.OPERATION
    assert "coisa_qualquer" in (warning or "")


def test_dependencia_invalida_e_descartada_sem_derrubar_o_plano():
    depends, warnings = normalize_depends([0, "2", "x", True, 1])

    assert depends == [0, 2, 1]
    assert len(warnings) == 2


def test_covers_normalizado_em_lista_uniforme():
    assert normalize_covers(["R1"]) == [{"req": "R1", "partial": False, "part": ""}]
    assert normalize_covers({"req": "R2", "partial": True, "part": "API"}) == [
        {"req": "R2", "partial": True, "part": "API"}
    ]
    assert normalize_covers(None) is None


def test_plano_com_kind_fora_do_enum_sobrevive():
    payload, warnings = normalize_plan_payload(
        {
            "subtasks": [
                {"title": "Ler", "objective": "ler o arquivo", "kind": "operation"},
                {
                    "title": "Resposta final",
                    "objective": "responder",
                    "kind": "final_answer",
                    "metadata": {"final_answer": True},
                },
            ]
        }
    )

    plan = DecompositionResult.model_validate(payload)
    assert len(plan.subtasks) == 2
    assert plan.subtasks[1].kind == TaskKind.OPERATION
    assert plan.subtasks[1].metadata["final_answer"] is True


def test_plano_sem_subtarefas_e_sinalizado():
    payload, warnings = normalize_plan_payload({"subtasks": []})

    assert payload["subtasks"] == []
    assert warnings


def test_etapa_de_resposta_final_ganha_os_metadados_canonicos():
    payload, _ = normalize_plan_payload(
        {
            "subtasks": [
                {"title": "Concluir", "objective": "concluir", "kind": "resposta_final"},
            ]
        }
    )

    meta = payload["subtasks"][0]["metadata"]
    assert meta["final_answer"] is True
    assert meta["model_operation"] is True


def test_verificacao_de_tipo_inexistente_e_reparada_antes_de_executar(session, tmp_path):
    """Um verificador que não existe só falharia na execução, depois do trabalho já feito."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    root = TaskService(session).create_task(
        project.id, TaskCreate(title="Raiz", objective="Criar a.py")
    )
    root.status = TaskStatus.PLANNING.value
    session.flush()
    tasks = TaskService(session)
    kid = tasks.create_task(
        project.id,
        TaskCreate(
            title="Conferir",
            objective="conferir",
            parent_id=root.id,
            metadata={"verification": {"type": "search_grep", "pattern": "def"}},
        ),
    )
    session.flush()

    result = validate_children(
        session, root, project_root=str(tmp_path), run_config=None, max_tasks=None
    )
    assert "unknown_verification" in {i.code for i in result.issues}

    validate_and_repair(
        session, root, project_root=str(tmp_path), run_config=None, max_tasks=None, run_id=None
    )
    assert kid.metadata_json.get("verification") is None
    # A etapa não desaparece: sem outra ação, ela vira operação do modelo.
    assert kid.metadata_json.get("model_operation") is True


def test_edicao_com_trecho_inexistente_vira_operacao_do_modelo(session, tmp_path):
    """O modelo planeja a edição com o trecho que acredita existir. Se não existe, a etapa falha
    de certeza — melhor virar operação do modelo, que inspeciona e aplica."""
    (tmp_path / "app.py").write_text("def hello():\n    return 'oi'\n", encoding="utf-8")
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    root = TaskService(session).create_task(
        project.id, TaskCreate(title="Raiz", objective="Criar a função dobro")
    )
    root.status = TaskStatus.PLANNING.value
    session.flush()
    tasks = TaskService(session)
    kid = tasks.create_task(
        project.id,
        TaskCreate(
            title="Editar",
            objective="editar",
            parent_id=root.id,
            metadata={
                "tool": "edit_file",
                "tool_args": {
                    "path": "app.py",
                    "old_string": "def hello(): return 'oi'",
                    "new_string": "def hello(): return 'oi'\ndef dobro(x): return x*2",
                },
            },
        ),
    )
    session.flush()

    result = validate_children(
        session, root, project_root=str(tmp_path), run_config=None, max_tasks=None
    )
    assert "edit_anchor_missing" in {i.code for i in result.issues}

    validate_and_repair(
        session, root, project_root=str(tmp_path), run_config=None, max_tasks=None, run_id=None
    )
    assert kid.metadata_json.get("tool") is None
    assert kid.metadata_json.get("model_operation") is True


def test_edicao_com_trecho_presente_e_preservada(session, tmp_path):
    (tmp_path / "app.py").write_text("def hello():\n    return 'oi'\n", encoding="utf-8")
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    root = TaskService(session).create_task(
        project.id, TaskCreate(title="Raiz", objective="Criar a função dobro")
    )
    root.status = TaskStatus.PLANNING.value
    session.flush()
    kid = TaskService(session).create_task(
        project.id,
        TaskCreate(
            title="Editar",
            objective="editar",
            parent_id=root.id,
            metadata={
                "tool": "edit_file",
                "tool_args": {
                    "path": "app.py",
                    "old_string": "def hello():\n    return 'oi'\n",
                    "new_string": "def hello():\n    return 'ola'\n",
                },
            },
        ),
    )
    session.flush()

    result = validate_and_repair(
        session, root, project_root=str(tmp_path), run_config=None, max_tasks=None, run_id=None
    )

    assert "edit_anchor_missing" not in {i.code for i in result.issues}
    assert kid.metadata_json.get("tool") == "edit_file"
