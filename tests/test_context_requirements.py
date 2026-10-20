"""
Arquivo: tests/test_context_requirements.py
Nome: test_context_requirements.py
Propósito: Verificar que os requisitos canônicos chegam ao prompt da etapa e sobrevivem ao aperto de contexto.
Responsabilidade: camada de testes — montagem do contexto da etapa com requisitos, objetivo global, regras do projeto e descarte do dispensável.
Componentes: requisitos no prompt, objetivo global e regra do projeto como obrigatórios, descarte do conteúdo não essencial, componente vazio e requisitos da etapa.
Dependências: agent.context.assembler, agent.context.operation_builder e agent.orchestrator.requirements.
Observações: banco temporário por teste; a montagem do contexto é determinística.

Regressões do contexto da operação.

O critério de aceite canônico (os requisitos da raiz) nunca chegava ao prompt da etapa: o
modelo executava sem saber o que tinha de provar, e a validação depois apontava o requisito
como não comprovado. Além disso, o objetivo global e as regras do projeto eram componentes
descartáveis — o modelo perdia o "porquê" e as restrições canônicas quando o contexto
aperto.
"""

from pathlib import Path

import pytest

from agent.config import Settings
from agent.context.assembler import build_operation_context
from agent.context.budget import ContextBudgetError
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ProjectCreate, TaskCreate
from agent.orchestrator.requirements import ensure_requirements
from agent.persistence.database import build_session_factory, init_db
from agent.providers.base import ModelProfile
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService


@pytest.fixture
def session(tmp_path: Path):
    """Abre uma sessão do banco temporário e a fecha ao fim do teste."""
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


def _contexto(**extra):
    """Monta o contexto de operação com um perfil de modelo padrão e ajustes pontuais."""
    base = dict(
        global_rules="regras",
        project_rules="memória do projeto",
        objective="fazer a coisa",
        technical="técnico",
        acceptance="critério",
        tools_summary="ferramentas",
        output_format="formato",
    )
    base.update(extra)
    return build_operation_context(ModelProfile(model_id="m", input_budget=4000, context_limit=8192), **base)


def test_requisitos_chegam_ao_prompt():
    """Os requisitos obrigatórios aparecem no prompt montado para a etapa."""
    result = _contexto(requirements="Requisitos obrigatórios:\n- R1: criar a função dobro")

    corpo = result.messages[-1].content
    assert "## requisitos" in corpo
    assert "R1: criar a função dobro" in corpo


def test_objetivo_global_e_regra_do_projeto_sao_obrigatorios():
    """Objetivo global e regras do projeto são o 'porquê' e as restrições: não podem ser cortados."""
    result = _contexto(global_objective="o objetivo maior", project_rules="a regra canônica")

    corpo = result.messages[-1].content
    assert "o objetivo maior" in corpo
    assert "a regra canônica" in corpo
    assert result.dropped == []


def test_conteudo_nao_essencial_e_o_que_sai_quando_falta_espaco():
    """Quando falta espaço, o conteúdo descartável sai e objetivo, requisitos e regra do projeto permanecem."""
    perfil = ModelProfile(model_id="m", input_budget=1200, context_limit=8192)
    result = build_operation_context(
        perfil,
        global_rules="regras",
        project_rules="memória",
        objective="fazer a coisa",
        technical="código técnico importante " * 200,
        acceptance="critério",
        tools_summary="ferramentas " * 200,
        output_format="formato",
        requirements="R1: algo",
    )

    assert result.dropped, "o contexto grande precisa dar lugar a algo"
    # O que não pode faltar: objetivo, requisitos, regras do projeto.
    corpo = result.messages[-1].content
    assert "fazer a coisa" in corpo
    assert "R1: algo" in corpo
    assert "memória" in corpo


def test_componente_vazio_nao_gera_cabecalho():
    """Um componente vazio não produz cabeçalho no prompt."""
    result = _contexto(global_objective="")

    assert "## objetivo-global" not in result.messages[-1].content


def test_requisitos_da_tarefa_aparecem_no_contexto_da_etapa(session, tmp_path):
    """A etapa recebe os requisitos que ela cobre, com o critério de cada um."""
    from agent.context.operation_builder import OperationContextBuilder

    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(
        project.id,
        TaskCreate(title="Raiz", objective="Pedido:\n- criar a função dobro em app.py"),
    )
    root.status = TaskStatus.PLANNING.value
    ensure_requirements(session, root)
    child = tasks.create_task(
        project.id,
        TaskCreate(
            title="Etapa",
            objective="criar a função dobro",
            parent_id=root.id,
            metadata={"covers": ["R1"]},
        ),
    )
    session.flush()

    budget, _ = OperationContextBuilder(session).build_for_task(
        project_id=project.id,
        root_path=str(tmp_path),
        task=child,
        profile=ModelProfile(model_id="m", input_budget=4000, context_limit=8192),
    )

    corpo = budget.messages[-1].content
    assert "## requisitos" in corpo
    assert "R1" in corpo
    assert "dobro" in corpo


def test_requisito_que_a_etapa_nao_cobre_nao_aparece(session, tmp_path):
    """O requisito que a etapa não cobre não entra no contexto dela."""
    from agent.context.operation_builder import OperationContextBuilder

    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(
        project.id,
        TaskCreate(title="Raiz", objective="Pedido:\n- criar a.py\n- criar b.py"),
    )
    root.status = TaskStatus.PLANNING.value
    ensure_requirements(session, root)
    child = tasks.create_task(
        project.id,
        TaskCreate(
            title="Etapa",
            objective="criar a.py",
            parent_id=root.id,
            metadata={"covers": ["R1"]},
        ),
    )
    session.flush()

    budget, _ = OperationContextBuilder(session).build_for_task(
        project_id=project.id,
        root_path=str(tmp_path),
        task=child,
        profile=ModelProfile(model_id="m", input_budget=4000, context_limit=8192),
    )

    corpo = budget.messages[-1].content
    assert "R1" in corpo
    assert "R2" not in corpo
