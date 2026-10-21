"""
Arquivo: tests/test_automation_chat_execution.py
Nome: test_automation_chat_execution.py
Propósito: Verificar que a automação criada pelo chat realmente dispara, de uma vez só, e sobrevive ao reinício.
Responsabilidade: camada de testes — execução pelo supervisor, idempotência, recuperação e reconciliação do run.
Componentes: supervisor, dispatcher, executor e o serviço de automações do chat.
Dependências: agent.automation.chat_service, agent.automation.supervisor, agent.automation.executor.
Observações: banco temporário por teste; a ação é de script, então nenhum modelo é chamado.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from agent.automation.chat_service import AutomationChatService
from agent.automation.enums import AutomationState, FiringState
from agent.automation.executor import AutomationExecutor
from agent.automation.supervisor import AutomationSupervisor
from agent.config import get_settings
from agent.domain.enums import RunStatus
from agent.persistence.database import build_session_factory, create_db_engine, init_db
from agent.persistence.models import (
    AutomationFiringModel,
    AutomationModel,
    ExecutionRunModel,
    ProjectModel,
)


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Banco isolado por teste."""
    url = f"sqlite:///{tmp_path / 'chat-exec.db'}"
    monkeypatch.setenv("CALLIDUS_TEST_DATABASE_URL", url)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    settings = get_settings()
    engine = init_db(create_db_engine(settings), settings)
    return engine, build_session_factory(engine), settings


@pytest.fixture
def project(db, tmp_path):
    """Projeto do teste."""
    _engine, factory, _settings = db
    session = factory()
    row = ProjectModel(name="projeto", root_path=str(tmp_path))
    session.add(row)
    session.commit()
    session.close()
    return row


def _script(tmp_path: Path) -> Path:
    """Script executável usado pela automação de teste."""
    path = tmp_path / "alvo.sh"
    path.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.mark.asyncio
async def test_automacao_do_chat_dispara_uma_vez_e_recupera_apos_reinicio(db, project, tmp_path):
    """A automação criada pelo chat é recuperada no reinício e o disparo ocorre uma única vez."""
    _engine, factory, settings = db
    session = factory()
    script = _script(tmp_path)
    service = AutomationChatService(session, settings, project_id=project.id)
    created = await service.create(
        name="Verificação por script",
        objective="Registrar a verificação",
        schedule="a cada 5 minutos",
        action_kind="script",
        command=[str(script)],
        allow_scripts=True,
        allowed_commands=[str(script)],
    )
    automation_id = created["automation"]["id"]
    service.set_state(
        automation_id,
        "enabled",
        confirmation_token=created["automation"]["confirmation_token"],
    )
    # O horário do disparo já passou: o runtime tem de recolhê-lo.
    row = session.get(AutomationModel, uuid.UUID(automation_id))
    row.last_run_at = datetime.now(timezone.utc) - timedelta(seconds=600)
    row.next_run_at = datetime.now(timezone.utc) - timedelta(seconds=300)
    session.commit()
    session.close()

    # "Reinício": um supervisor novo, com sessões novas sobre o mesmo banco.
    supervisor = AutomationSupervisor(settings, session_factory=factory)
    summary = await supervisor.tick()
    assert summary["dispatched"]["created"]

    session = factory()
    firings = list(session.scalars(select(AutomationFiringModel)).all())
    assert len(firings) == 1
    assert firings[0].state == FiringState.COMPLETED.value
    session.close()

    # Um segundo tique (polling repetido) não cria outro disparo.
    supervisor = AutomationSupervisor(settings, session_factory=factory)
    second = await supervisor.tick()
    assert not second["dispatched"]["created"]
    session = factory()
    assert len(list(session.scalars(select(AutomationFiringModel)).all())) == 1
    session.close()


@pytest.mark.asyncio
async def test_execucao_callidus_cria_tarefa_e_run_e_o_historico_reflete_o_fim(db, project):
    """A ação Callidus cria a tarefa raiz e o run; o histórico fecha quando o run termina."""
    _engine, factory, settings = db
    session = factory()
    service = AutomationChatService(session, settings, project_id=project.id)
    created = await service.create(
        name="Análise noturna",
        objective="Analisar o projeto ERP e rodar os testes",
        schedule="todos os dias às 23h",
    )
    automation_id = created["automation"]["id"]
    result = await service.run_now(automation_id)
    assert result["success"] is True
    assert result["firing"]["run_id"]
    assert result["firing"]["task_id"]
    assert result["firing"]["state"] == FiringState.RUNNING.value

    # O run termina: a reconciliação fecha o disparo.
    run = session.get(ExecutionRunModel, uuid.UUID(result["firing"]["run_id"]))
    run.status = RunStatus.COMPLETED.value
    session.commit()
    executor = AutomationExecutor(session, settings)
    executor.reconcile()
    session.commit()
    session.expire_all()
    firing = session.get(AutomationFiringModel, uuid.UUID(result["firing"]["id"]))
    assert firing.state == FiringState.COMPLETED.value

    history = service.history(automation_id)
    assert history["firings"][0]["state"] == FiringState.COMPLETED.value
    assert history["firings"][0]["run_id"] == result["firing"]["run_id"]


@pytest.mark.asyncio
async def test_automacao_desabilitada_nao_dispara(db, project, tmp_path):
    """Automação desabilitada não é recolhida pelo runtime."""
    _engine, factory, settings = db
    session = factory()
    script = _script(tmp_path)
    service = AutomationChatService(session, settings, project_id=project.id)
    await service.create(
        name="Verificação por script",
        objective="Registrar a verificação",
        schedule="a cada 5 minutos",
        action_kind="script",
        command=[str(script)],
        allow_scripts=True,
        allowed_commands=[str(script)],
    )
    session.close()

    supervisor = AutomationSupervisor(settings, session_factory=factory)
    summary = await supervisor.tick()
    assert not summary["dispatched"]["created"]
    session = factory()
    assert len(list(session.scalars(select(AutomationFiringModel)).all())) == 0
    session.close()


@pytest.mark.asyncio
async def test_dependencia_ausente_nao_produz_sucesso(db, project, tmp_path):
    """Dependência indisponível é registrada e reagendada, sem inferência e sem sucesso falso."""
    _engine, factory, settings = db
    session = factory()
    service = AutomationChatService(session, settings, project_id=project.id)
    created = await service.create(
        name="Verificação por script",
        objective="Registrar a verificação",
        schedule="a cada 5 minutos",
        action_kind="script",
        command=[str(tmp_path / "inexistente.sh")],
        allow_scripts=True,
        allowed_commands=[str(tmp_path / "inexistente.sh")],
        dependencies=[
            {
                "kind": "script",
                "name": str(tmp_path / "inexistente.sh"),
                "params": {"required": True},
            }
        ],
    )
    row = session.get(AutomationModel, uuid.UUID(created["automation"]["id"]))
    row.state = AutomationState.ENABLED.value
    row.last_run_at = datetime.now(timezone.utc) - timedelta(seconds=600)
    row.next_run_at = datetime.now(timezone.utc) - timedelta(seconds=300)
    session.commit()
    session.close()

    supervisor = AutomationSupervisor(settings, session_factory=factory)
    await supervisor.tick()
    session = factory()
    firings = list(session.scalars(select(AutomationFiringModel)).all())
    assert firings
    assert firings[0].state != FiringState.COMPLETED.value
    session.close()
