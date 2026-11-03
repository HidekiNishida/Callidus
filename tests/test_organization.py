"""
Arquivo: tests/test_organization.py
Nome: test_organization.py
Propósito: verificar as regras puras da organização de engenharia — catálogo, propriedade, seleção do responsável, independência da revisão, portões e etapa do fluxo.
Responsabilidade: camada de testes — domínio (`agent.domain.organization`, `agent.domain.work_flow`), sem banco nem rede.
Componentes: testes de catálogo, de `owner_of`, de `select_assignment`, de `reviewer_allowed`, de `evaluate_gates`, `stage_for` e `evaluate_delivery`.
Dependências: agent.domain.organization, agent.domain.work_flow, pytest.
Observações: o domínio é importável sem FastAPI e sem SQLAlchemy — o teste de importação prova isso.
"""
from __future__ import annotations

import subprocess
import sys

from agent.domain.organization import (
    ROLES,
    owner_of,
    reviewer_allowed,
    select_assignment,
    validate_catalog,
)
from agent.domain.work_flow import WorkSnapshot, WorkStage, evaluate_delivery, evaluate_gates, stage_for


def _assignment(**extra):
    """Atribuição mínima de um desenvolvedor backend revisado pelo QA."""
    base = {"role": "backend_developer", "reviewer_role": "qa_engineer", "team": "core_engineering", "risk": "low"}
    return {**base, **extra}


def test_o_catalogo_e_coerente():
    """Nenhum padrão com dois donos, nenhuma referência quebrada, nenhuma área protegida sem coordenação."""
    assert validate_catalog() == []


def test_o_dominio_nao_depende_de_fastapi_nem_sqlalchemy():
    """Importar o domínio da organização não carrega FastAPI nem SQLAlchemy (AGENTS.md §2)."""
    code = (
        "import sys; import agent.domain.organization, agent.domain.work_flow; "
        "print(any(m.split('.')[0] in {'fastapi', 'sqlalchemy'} for m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_a_regra_mais_especifica_vence():
    """Arquivo exato vence pasta, pasta vence nome de pasta genérico, que vence extensão."""
    assert owner_of("src/agent/domain/state_machine.py").protected is True
    assert owner_of("src/agent/domain/enums.py").protected is False
    assert owner_of("./src/agent/services/task_service.py").team == "core_engineering"
    assert owner_of("app/tests/test_x.py").role == "test_engineer"
    assert owner_of("app/models.py").role == "backend_developer"
    assert owner_of("web/static/assets/app/main.js").team == "product_experience"
    assert owner_of("LICENSE") is None


def test_persistencia_vai_para_dados_com_revisao_do_qa_e_coordenacao_do_arquiteto():
    """O exemplo da missão: mudança de persistência é Core Engineering, dados, revisada pelo QA."""
    a = select_assignment(objective="corrigir persistência", paths=["src/agent/persistence/models.py"])
    assert (a.team, a.role, a.reviewer_role, a.domain) == (
        "core_engineering", "backend_developer", "qa_engineer", "data_engineering"
    )
    assert a.risk == "high"
    assert "software_architect" in a.coordination
    assert a.rationale and a.confidence == 1.0


def test_escopo_em_varias_areas_vira_coordenacao_e_risco_medio():
    """Escopo que cruza equipes escolhe a maioria e registra as demais como coordenação."""
    a = select_assignment(
        objective="mostrar o novo campo",
        paths=["web/static/assets/app/main.js", "web/static/assets/app/store.js", "src/agent/api/task_routes.py"],
    )
    assert a.role == "frontend_developer"
    assert a.risk == "medium"
    assert a.complexity == "medium"
    assert set(a.affected_modules) == {"web/static/", "src/agent/api/"}


def test_sem_arquivo_o_objetivo_e_a_estrategia_decidem():
    """Sem escopo, a especialidade da estratégia vence as palavras; sem nada, a atribuição pede investigação."""
    assert select_assignment(objective="escreva testes da calculadora").role == "test_engineer"
    assert select_assignment(objective="algo", lead_specialty="technical_writing").role == "knowledge_steward"
    vague = select_assignment(objective="faça o que achar melhor")
    assert vague.needs_investigation is True
    assert vague.confidence < 0.5


def test_tarefa_raiz_fica_com_o_tech_lead():
    """O objetivo do usuário é coordenado pelo tech lead, revisado pelo QA."""
    a = select_assignment(objective="corrigir o bug do login", kind="objective")
    assert (a.role, a.reviewer_role) == ("tech_lead", "qa_engineer")
    assert a.complexity == "high"


def test_ninguem_aprova_o_proprio_trabalho():
    """O executor não revisa a si mesmo; um papel sem relação com o executor também não."""
    for role in ROLES:
        assert reviewer_allowed(role, role) is False
    assert reviewer_allowed("backend_developer", "qa_engineer") is True
    assert reviewer_allowed("backend_developer", "frontend_developer") is False
    assert reviewer_allowed("frontend_developer", "product_owner") is True


def _snap(status: str, **extra) -> WorkSnapshot:
    """Retrato padrão: objetivo, aceite e atribuição de um desenvolvedor backend."""
    data = {"objective": "fazer x", "acceptance": "x funciona", "assignment": _assignment()}
    data.update(extra)
    return WorkSnapshot(status=status, **data)


def test_g0_reprova_sem_responsavel_nem_aceite():
    """Planejamento sem critério de aceite e sem responsável não passa no G0."""
    gates = evaluate_gates(WorkSnapshot(status="PENDING", objective="x"))
    g0 = gates[0]
    assert g0.state == "failed"
    assert any("responsável" in b for b in g0.blocking)
    assert stage_for(WorkSnapshot(status="PENDING", objective="x"), gates) == WorkStage.INBOX


def test_escrita_fora_do_escopo_reprova_o_g1():
    """Arquivo alterado fora de `allowed_files` reprova a implementação."""
    snap = _snap("COMPLETED", allowed_files=["src/a.py"], changed_files=["src/a.py", "src/b.py"],
                 evidences=[{"verifier": "pytest", "passed": True}])
    g1 = evaluate_gates(snap)[1]
    assert g1.state == "failed"
    assert "src/b.py" in g1.blocking[0]


def test_reprovacao_que_depois_passa_aprova_mas_nao_na_primeira():
    """A última evidência decide o G2; a reprovação anterior fica registrada como retrabalho."""
    snap = _snap("COMPLETED", changed_files=["a.py"],
                 evidences=[{"verifier": "pytest", "passed": False}, {"verifier": "pytest", "passed": True}])
    g2 = evaluate_gates(snap)[2]
    assert g2.state == "passed"
    first = next(c for c in g2.checks if c["name"] == "aprovada na primeira verificação")
    assert first["ok"] is False and first["eliminatory"] is False


def test_revisao_independente_reprova_tarefa_concluida():
    """Concluída pelo runtime e reprovada pelo QA: G3 reprova, a etapa é retrabalho e a entrega não é aceita."""
    snap = _snap("COMPLETED", changed_files=["a.py"], evidences=[{"verifier": "pytest", "passed": True}],
                 reviews=[{"role": "qa_engineer", "decision": "rejected", "reason": "não trata vazio"}])
    gates = evaluate_gates(snap)
    assert gates[3].state == "failed"
    assert stage_for(snap, gates) == WorkStage.REWORK
    evaluation = evaluate_delivery(snap, gates)
    assert evaluation["accepted"] is False
    assert "Qualidade" in evaluation["eliminatory_failures"]


def test_area_protegida_espera_revisao_registrada():
    """Mudança em área protegida fica em auditoria técnica até um revisor independente aprovar."""
    assignment = _assignment(protected_files=["src/agent/persistence/models.py"], risk="high")
    base = {"changed_files": ["src/agent/persistence/models.py"], "evidences": [{"verifier": "pytest", "passed": True}],
            "assignment": assignment, "is_root": True}
    waiting = _snap("COMPLETED", **base)
    assert stage_for(waiting, evaluate_gates(waiting)) == WorkStage.TECHNICAL_AUDIT
    approved = _snap("COMPLETED", reviews=[{"role": "qa_engineer", "decision": "approved"}], **base)
    gates = evaluate_gates(approved)
    assert [g.state for g in gates] == ["passed"] * 5
    assert stage_for(approved, gates) == WorkStage.DONE
    assert evaluate_delivery(approved, gates)["accepted"] is True


def test_autoaprovacao_nao_conta_e_e_apontada():
    """A aprovação do próprio executor não satisfaz a revisão e reprova o G3."""
    snap = _snap("COMPLETED", changed_files=["a.py"], evidences=[{"verifier": "pytest", "passed": True}],
                 reviews=[{"role": "backend_developer", "decision": "approved"}])
    g3 = evaluate_gates(snap)[3]
    assert g3.state == "failed"


def test_etapa_segue_o_status_sem_segunda_maquina_de_estados():
    """Cada `TaskStatus` cai numa etapa previsível."""
    expected = {
        "PLANNING": WorkStage.ANALYSIS,
        "READY": WorkStage.READY,
        "RUNNING": WorkStage.IN_PROGRESS,
        "VERIFYING": WorkStage.IMPLEMENTATION_COMPLETE,
        "RETRY_PENDING": WorkStage.REWORK,
        "BLOCKED": WorkStage.BLOCKED,
        "FAILED": WorkStage.FAILED,
        "CANCELLED": WorkStage.CANCELLED,
    }
    for status, stage in expected.items():
        snap = _snap(status)
        assert stage_for(snap, evaluate_gates(snap)) == stage, status


def test_subtarefa_concluida_e_aprovada_fica_integrada():
    """Fora da raiz, a etapa final é INTEGRATED; subtarefa filha aberta segura a integração."""
    snap = _snap("COMPLETED", changed_files=["a.py"], evidences=[{"verifier": "pytest", "passed": True}])
    assert stage_for(snap, evaluate_gates(snap)) == WorkStage.INTEGRATED
    parent = _snap("COMPLETED", changed_files=["a.py"], evidences=[{"verifier": "pytest", "passed": True}],
                   children=["COMPLETED", "RUNNING"])
    gates = evaluate_gates(parent)
    assert gates[4].state == "failed"
    assert stage_for(parent, gates) == WorkStage.READY_FOR_INTEGRATION
