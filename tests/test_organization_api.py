"""
Arquivo: tests/test_organization_api.py
Nome: test_organization_api.py
Propósito: verificar, pela API e pelo estado persistido, os cenários de aceitação da organização de engenharia (A–J): contrato de trabalho, especialização, handoff, falha, revisão independente, mudança arquitetural, retomada, autoavaliação, contexto limitado e entrega completa.
Responsabilidade: camada de testes — rotas de `agent.api.organization_routes` e ganchos em `AgentService` e `OperationContextBuilder`.
Componentes: fixtures `client` e `project`; um teste por cenário.
Dependências: agent.api, agent.services.agent_service, agent.services.organization_service, agent.persistence.models, fastapi.testclient, pytest.
Observações: o banco de teste é o temporário que `Settings` escolhe sob pytest (compartilhado entre testes, por isso toda métrica é filtrada por projeto), worker de fundo desligado, nenhum modelo real; evidências e status são gravados direto no banco para simular o que o portão de verificação faria.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.api import deps
from agent.config import Settings
from agent.domain.enums import AttemptKind
from agent.persistence.models import AgentModel, EvidenceModel, OperationAttemptModel, TaskModel
from agent.services.agent_service import AgentService


@pytest.fixture
def client(tmp_path: Path):
    """Cliente de teste da API com banco temporário e worker de fundo desligado."""
    settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)

    def override_settings():
        """Devolve as configurações do teste."""
        return settings

    deps._engine = None
    deps._session_factory = None
    from agent.api.main import app

    app.dependency_overrides[deps.read_settings] = override_settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    deps._engine = None
    deps._session_factory = None


@pytest.fixture
def project(client: TestClient) -> dict:
    """Projeto vazio."""
    return client.post("/projects", json={"name": "org", "root_path": "/tmp/org"}).json()


def _task(client: TestClient, project: dict, **body) -> dict:
    """Cria uma tarefa pela API."""
    body.setdefault("title", "t")
    body.setdefault("objective", "fazer algo")
    return client.post(f"/projects/{project['id']}/tasks", json=body).json()


class _Db:
    """Sessão direta ao banco do teste, confirmada ao sair."""

    def __enter__(self):
        self.session = deps.get_session_factory()()
        return self.session

    def __exit__(self, *exc):
        if exc[0] is None:
            self.session.commit()
        self.session.close()


def _finish(task_id: str, *, verdicts: list[bool], status: str = "COMPLETED", changed: list[str] | None = None) -> None:
    """Simula o caminho de execução: escrita registrada, evidências do portão e status final."""
    with _Db() as s:
        task = s.get(TaskModel, uuid.UUID(task_id))
        from agent.persistence.models import ExecutionRunModel

        run = ExecutionRunModel(project_id=task.project_id, root_task_id=task.id, status="active")
        s.add(run)
        s.flush()
        for path in changed or []:
            s.add(OperationAttemptModel(run_id=run.id, task_id=task.id, kind=AttemptKind.TOOL.value,
                                        provider="write_file", request_json={"path": path}, success=True))
        for ok in verdicts:
            s.add(OperationAttemptModel(run_id=run.id, task_id=task.id, kind=AttemptKind.VERIFICATION.value,
                                        provider="pytest", response_json={"passed": ok}, success=ok))
            s.add(EvidenceModel(task_id=task.id, verifier="pytest", passed=ok,
                                summary="testes passaram" if ok else "1 teste falhou"))
            s.flush()
        task.status = status
        from datetime import UTC, datetime

        task.completed_at = datetime.now(UTC) if status == "COMPLETED" else None


def test_a_nova_tarefa_ganha_contrato_com_responsavel(client, project):
    """Cenário A: objetivo vira contrato de trabalho com domínio, responsável, revisor e G0 aprovado."""
    task = _task(client, project, objective="escreva testes para o parser", acceptance_criteria="pytest passa")
    item = client.get(f"/tasks/{task['id']}/work-item").json()
    assert item["assignment"]["role"] == "tech_lead"  # tarefa raiz: o tech lead coordena
    assert item["assignment"]["reviewer_role"] == "qa_engineer"
    assert item["assignment"]["rationale"]
    gates = client.get(f"/tasks/{task['id']}/gates").json()
    assert gates["gates"][0]["state"] == "passed"
    assert gates["stage"] == "READY"


def test_b_subtarefas_em_modulos_diferentes_tem_especialistas_diferentes(client, project):
    """Cenário B: cada subtarefa recebe o dono do próprio escopo, e o agente guarda a atribuição."""
    root = _task(client, project, objective="mostrar a etapa da tarefa na interface")
    api = _task(client, project, objective="expor a etapa", parent_id=root["id"], kind="operation",
                metadata={"allowed_files": ["src/agent/api/task_routes.py"]})
    ui = _task(client, project, objective="exibir a etapa", parent_id=root["id"], kind="operation",
               metadata={"allowed_files": ["web/static/assets/app/components/details.js"]})
    with _Db() as s:
        agents = AgentService(s)
        a_api = agents.ensure_agent(uuid.UUID(api["id"]))
        a_ui = agents.ensure_agent(uuid.UUID(ui["id"]))
        assert a_api.metadata_json["assignment"]["role"] == "backend_developer"
        assert a_ui.metadata_json["assignment"]["role"] == "frontend_developer"
    org = client.get("/organization", params={"project_id": project["id"]}).json()
    roles = {a["role"] for a in org["agents"]}
    assert {"tech_lead", "backend_developer", "frontend_developer"} <= roles
    api_item = client.get(f"/tasks/{api['id']}/work-item").json()
    assert "software_architect" in api_item["assignment"]["coordination"]  # contrato HTTP compartilhado


def test_c_handoff_preserva_a_investigacao(client, project):
    """Cenário C: o resultado do filho vira handoff estruturado que o próximo lê sem reinvestigar."""
    root = _task(client, project, objective="corrigir o cálculo")
    child = _task(client, project, objective="achar a causa", parent_id=root["id"], kind="operation",
                  metadata={"allowed_files": ["calc.py"]})
    with _Db() as s:
        agents = AgentService(s)
        agent = agents.ensure_agent(uuid.UUID(child["id"]))
        agents.record_finding(agent.id, "a divisão usa inteiro", kind="hypothesis")
        agents.record_finding(agent.id, "o arredondamento não é o problema", kind="discarded_hypothesis")
    _finish(child["id"], verdicts=[True], changed=["calc.py"])
    with _Db() as s:
        task = s.get(TaskModel, uuid.UUID(child["id"]))
        task.consolidated_result_json = {"summary": "troca // por /", "verified": True}
        s.flush()
        AgentService(s).record_task_result(task.id)
        stored = s.get(AgentModel, agent.id).metadata_json["handoff"]
    assert stored["files_changed"] == ["calc.py"]
    assert stored["hypotheses"] == ["a divisão usa inteiro"]
    assert stored["discarded_hypotheses"] == ["o arredondamento não é o problema"]
    assert stored["evidence_ids"] and stored["next_owner"] == "qa_engineer"
    fresh = client.get(f"/tasks/{child['id']}/handoff").json()
    assert fresh["files_changed"] == ["calc.py"]
    assert client.get(f"/tasks/{child['id']}/work-item").json()["handoff"]["work_item_id"] == stored["work_item_id"]


def test_d_falha_registrada_e_recuperada(client, project):
    """Cenário D: a reprovação fica como evidência, a recuperação aprova e o retrabalho é contado."""
    task = _task(client, project, objective="ajustar o parser", acceptance_criteria="testes passam",
                 metadata={"allowed_files": ["parser.py"]})
    _finish(task["id"], verdicts=[False, True], changed=["parser.py"])
    gates = client.get(f"/tasks/{task['id']}/gates").json()
    g2 = gates["gates"][2]
    assert g2["state"] == "passed"
    assert any(c["name"] == "aprovada na primeira verificação" and c["ok"] is False for c in g2["checks"])
    metrics = client.get("/api/intelligence/metrics/delivery", params={"project_id": project["id"]}).json()["metrics"]
    assert metrics["rework_rate"]["value"] == 1.0
    assert metrics["recovery_success"]["numerator"] == 1
    assert metrics["first_pass_acceptance"]["value"] == 0.0


def test_e_revisao_independente_pode_reprovar(client, project):
    """Cenário E: o executor não se aprova (422); o QA reprova e a etapa vira retrabalho."""
    task = _task(client, project, objective="ajustar o parser", acceptance_criteria="testes passam",
                 kind="operation", metadata={"allowed_files": ["parser.py"]})
    _finish(task["id"], verdicts=[True], changed=["parser.py"])
    executor = client.get(f"/tasks/{task['id']}/work-item").json()["assignment"]["role"]
    own = client.post(f"/tasks/{task['id']}/reviews", json={"role": executor, "decision": "approved"})
    assert own.status_code == 422
    no_reason = client.post(f"/tasks/{task['id']}/reviews", json={"role": "qa_engineer", "decision": "rejected"})
    assert no_reason.status_code == 422
    rejected = client.post(f"/tasks/{task['id']}/reviews",
                           json={"role": "qa_engineer", "decision": "rejected", "reason": "não trata entrada vazia"})
    assert rejected.status_code == 201
    gates = client.get(f"/tasks/{task['id']}/gates").json()
    assert gates["gates"][3]["state"] == "failed"
    assert gates["stage"] == "REWORK"
    assert gates["evaluation"]["accepted"] is False
    escape = client.get("/api/intelligence/metrics/delivery",
                        params={"project_id": project["id"]}).json()["metrics"]["defect_escape_rate"]
    assert (escape["numerator"], escape["denominator"]) == (1, 1)


def test_f_mudanca_arquitetural_exige_coordenacao(client, project):
    """Cenário F: contrato compartilhado e área protegida elevam o risco e seguram a auditoria técnica."""
    task = _task(client, project, objective="nova coluna de prioridade", kind="operation",
                 acceptance_criteria="migração idempotente",
                 metadata={"allowed_files": ["src/agent/persistence/models.py", "src/agent/persistence/database.py"]})
    item = client.get(f"/tasks/{task['id']}/work-item").json()
    assert item["assignment"]["risk"] == "high"
    assert "software_architect" in item["assignment"]["coordination"]
    assert item["scope"]["restricted_files"]
    _finish(task["id"], verdicts=[True], changed=["src/agent/persistence/models.py"])
    assert client.get(f"/tasks/{task['id']}/gates").json()["stage"] == "TECHNICAL_AUDIT"
    ok = client.post(f"/tasks/{task['id']}/reviews", json={"role": "qa_engineer", "decision": "approved"})
    assert ok.status_code == 201
    assert client.get(f"/tasks/{task['id']}/gates").json()["stage"] == "DONE"  # sem pai: é raiz


def test_g_atribuicao_sobrevive_a_interrupcao(client, project):
    """Cenário G: o contrato é estado persistido — outra sessão lê o mesmo, sem reatribuir."""
    task = _task(client, project, objective="ajustar o parser", kind="operation",
                 metadata={"allowed_files": ["parser.py"]})
    first = client.get(f"/tasks/{task['id']}/work-item").json()
    client.post(f"/tasks/{task['id']}/reviews", json={"role": "qa_engineer", "decision": "approved"})
    deps._engine = None
    deps._session_factory = None  # simula reinício do processo
    again = client.get(f"/tasks/{task['id']}/work-item").json()
    assert again["id"] == first["id"]
    assert again["created_at"] == first["created_at"]
    assert len(again["reviews"]) == 1


def test_h_indicadores_comparam_duas_versoes(client, project):
    """Cenário H: os indicadores distinguem uma entrega limpa de uma com retrabalho, com denominadores."""
    other = client.post("/projects", json={"name": "depois", "root_path": "/tmp/depois"}).json()
    before = _task(client, project, objective="v1", acceptance_criteria="ok", metadata={"allowed_files": ["a.py"]})
    after = _task(client, other, objective="v2", acceptance_criteria="ok", metadata={"allowed_files": ["a.py"]})
    _finish(before["id"], verdicts=[False, False, True], changed=["a.py"])
    _finish(after["id"], verdicts=[True], changed=["a.py"])
    m1 = client.get("/api/intelligence/metrics/delivery", params={"project_id": project["id"]}).json()["metrics"]
    m2 = client.get("/api/intelligence/metrics/delivery", params={"project_id": other["id"]}).json()["metrics"]
    assert m1["first_pass_acceptance"]["value"] == 0.0 and m2["first_pass_acceptance"]["value"] == 1.0
    assert m1["rework_rate"]["value"] > m2["rework_rate"]["value"]
    assert m2["lead_time"]["kind"] == "measured" and m2["lead_time"]["p95"] is None  # amostra pequena
    empty = client.post("/projects", json={"name": "vazio", "root_path": "/tmp/vazio"}).json()
    m0 = client.get("/api/intelligence/metrics/delivery", params={"project_id": empty["id"]}).json()["metrics"]
    assert m0["first_pass_acceptance"]["kind"] == "unavailable" and m0["first_pass_acceptance"]["value"] is None


def test_i_contexto_leva_so_a_linha_de_responsabilidade(client, project):
    """Cenário I: o contexto da operação recebe uma linha curta de responsabilidade, não o catálogo."""
    from agent.context.operation_builder import OperationContextBuilder

    task = _task(client, project, objective="nova coluna", kind="operation",
                 metadata={"allowed_files": ["src/agent/persistence/models.py"]})
    with _Db() as s:
        AgentService(s).ensure_agent(uuid.UUID(task["id"]))  # o runtime grava a atribuição aqui
        row = s.get(TaskModel, uuid.UUID(task["id"]))
        text, _paths = OperationContextBuilder(s)._contract_block(row)
    assert "responsável: Desenvolvedor backend" in text
    assert "revisor: QA engineer" in text
    assert "área protegida" in text
    assert len(text) < 400


def test_j_entrega_completa_chega_a_done(client, project):
    """Cenário J: planejada, implementada no escopo, verificada e revisada — DONE e aceita."""
    task = _task(client, project, objective="ajustar o parser", acceptance_criteria="testes passam",
                 metadata={"allowed_files": ["parser.py"]})
    _finish(task["id"], verdicts=[True], changed=["parser.py"])
    gates = client.get(f"/tasks/{task['id']}/gates").json()
    assert [g["state"] for g in gates["gates"]] == ["passed"] * 5
    assert gates["stage"] == "DONE"
    assert gates["evaluation"]["accepted"] is True
    board = client.get(f"/projects/{project['id']}/board").json()
    assert board[0]["stage"] == "DONE" and board[0]["gates"]["G4"] == "passed"


def test_ler_o_quadro_nao_grava_no_banco(client, project):
    """Abrir o quadro e os portões calcula a atribuição sem reescrever o `metadata_json` da tarefa."""
    task = _task(client, project, objective="ajustar o parser", metadata={"allowed_files": ["parser.py"]})
    client.get(f"/projects/{project['id']}/board")
    client.get(f"/tasks/{task['id']}/gates")
    client.get(f"/tasks/{task['id']}/work-item")
    with _Db() as s:
        assert "work_item" not in (s.get(TaskModel, uuid.UUID(task["id"])).metadata_json or {})


def test_rotas_tratam_inexistente_e_dono_de_caminho(client):
    """Tarefa inexistente é 404; o dono de um caminho é resolvido pela regra mais específica."""
    missing = uuid.uuid4()
    assert client.get(f"/tasks/{missing}/gates").status_code == 404
    assert client.get(f"/tasks/{missing}/work-item").status_code == 404
    assert client.post(f"/tasks/{missing}/reviews", json={"role": "qa_engineer", "decision": "approved"}).status_code == 404
    assert client.get(f"/projects/{missing}/board").status_code == 404
    owner = client.get("/organization/owner", params={"path": "src/agent/domain/state_machine.py"}).json()["owner"]
    assert owner["protected"] is True and owner["team_name"] == "Core Engineering"
