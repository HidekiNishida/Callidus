"""
Arquivo: tests/test_automation_end_to_end.py
Nome: test_automation_end_to_end.py
Propósito: Verificar o fluxo de aceitação de uma automação, de ponta a ponta e sem inferência.
Responsabilidade: camada de testes — criação, recuperação por outro processo, disparo, verificação de dependências, execução da ação e evidência persistida.
Componentes: fluxo completo sobrevivendo ao encerramento do processo, automação reativa a evento interno e automação de script determinístico.
Dependências: agent.automation.store, agent.automation.supervisor, agent.automation.contracts e agent.persistence.database.
Observações: banco SQLite temporário por teste; a recuperação é simulada abrindo um novo engine sobre o mesmo arquivo.

O fluxo de aceitação, de ponta a ponta e sem inferência.

1. A automação é criada e aprovada.
2. A interface e o processo principal são encerrados (a sessão e o engine são
   descartados — a próxima parte usa outra conexão).
3. O supervisor nativo carrega os dados do banco e recupera a automação.
4. O horário chega (ou a política de retomada se aplica) e o disparo é registrado.
5. As dependências são verificadas e as autorizadas são iniciadas.
6. A ação roda no destino correto, o resultado é verificado e a evidência fica
   persistida e disponível para inspeção posterior.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from agent.automation.contracts import (
    AutomationDefinition,
    CallidusAction,
    PermissionSpec,
    ScriptAction,
    TriggerSpec,
)
from agent.automation.enums import FiringState, MissedPolicy, TriggerKind
from agent.automation.store import AutomationService
from agent.automation.supervisor import AutomationSupervisor
from agent.config import get_settings
from agent.persistence.database import build_session_factory, create_db_engine, init_db
from agent.persistence.models import (
    AutomationFiringModel,
    AutomationModel,
    EventLogModel,
    ProjectModel,
)


@pytest.fixture
def db_url(tmp_path, monkeypatch):
    """Aponta o banco de teste para um arquivo SQLite temporário."""
    url = f"sqlite:///{tmp_path / 'e2e.db'}"
    monkeypatch.setenv("CALLIDUS_TEST_DATABASE_URL", url)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    return url


def _novo_engine(url: str):
    """Um 'processo' novo: engine nova sobre o mesmo arquivo."""
    from agent.config import get_settings

    settings = get_settings()
    return init_db(create_db_engine(settings), settings)


def test_fluxo_completo_sobrevive_ao_encerramento_do_processo(db_url, tmp_path):
    """A automação criada continua existindo e é executada por outro processo."""
    engine = _novo_engine(db_url)
    factory = build_session_factory(engine)

    session = factory()
    project = ProjectModel(name="projeto", root_path=str(tmp_path))
    session.add(project)
    session.commit()

    script = tmp_path / "trabalho.sh"
    script.write_text("#!/bin/sh\necho executado\n", encoding="utf-8")
    script.chmod(0o755)

    definition = AutomationDefinition(
        name="relatório da madrugada",
        project_id=str(project.id),
        trigger=TriggerSpec(kind=TriggerKind.CRON, cron="* * * * *", timezone="UTC"),
        action=ScriptAction(kind="script", command=[str(script)]),
        permissions=PermissionSpec(
            allow_scripts=True, allowed_commands=[str(script)], approved_resources=[str(script)]
        ),
        missed_policy=MissedPolicy.RUN_ONCE,
        state="enabled",
    )
    automation = AutomationService(session).create(definition)
    automation.last_run_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    session.commit()
    automation_id = automation.id
    session.close()
    engine.dispose()

    # ── a interface e o processo principal acabaram; outro processo assume ──
    engine = _novo_engine(db_url)
    factory = build_session_factory(engine)
    session = factory()
    recovered = session.get(AutomationModel, automation_id)
    assert recovered is not None
    assert recovered.name == "relatório da madrugada"
    assert recovered.state == "enabled"

    supervisor = AutomationSupervisor(get_settings(), session_factory=factory)
    summary = asyncio.run(supervisor.tick())
    assert summary["dispatched"]["created"], "o supervisor não despachou a automação vencida"
    assert any(item["state"] == FiringState.COMPLETED.value for item in summary["executed"])

    firings = list(session.scalars(select(AutomationFiringModel)).all())
    assert len(firings) == 1
    firing = firings[0]
    assert firing.state == FiringState.COMPLETED.value
    # A evidência fica persistida para inspeção posterior.
    assert firing.result_json["action"]["exit_code"] == 0
    assert "executado" in firing.result_json["action"]["stdout"]
    assert firing.result_json["dependencies"]["ok"] is True

    events = list(
        session.scalars(
            select(EventLogModel).where(EventLogModel.event_type == "automation.completed")
        ).all()
    )
    assert events
    session.close()
    engine.dispose()


def test_automacao_de_evento_interno_dispara_e_persiste(db_url, tmp_path):
    """Uma automação baseada em evento interno do Callidus."""
    engine = _novo_engine(db_url)
    factory = build_session_factory(engine)
    session = factory()
    project = ProjectModel(name="projeto", root_path=str(tmp_path))
    session.add(project)
    session.commit()

    automation = AutomationService(session).create(
        AutomationDefinition(
            name="reage a tarefa concluída",
            project_id=str(project.id),
            trigger=TriggerSpec(kind=TriggerKind.EVENT, event_type="task.completed"),
            action=CallidusAction(
                kind="callidus", objective="consolidar o que foi feito", autonomous=False
            ),
            state="enabled",
        )
    )
    session.commit()

    # Um evento interno acontece.
    session.add(
        EventLogModel(
            project_id=project.id,
            event_type="task.completed",
            payload_json={"title": "trabalho pronto"},
        )
    )
    session.commit()

    supervisor = AutomationSupervisor(get_settings(), session_factory=factory)
    asyncio.run(supervisor.tick())

    firings = list(
        session.scalars(
            select(AutomationFiringModel).where(
                AutomationFiringModel.automation_id == automation.id
            )
        ).all()
    )
    assert len(firings) == 1
    assert firings[0].result_json["event_type"] == "task.completed"
    assert firings[0].run_id is not None
    session.close()
    engine.dispose()


def test_automacao_de_script_nao_depende_de_inferencia(db_url, tmp_path):
    """O script determinístico roda sem qualquer chamada ao modelo."""
    engine = _novo_engine(db_url)
    factory = build_session_factory(engine)
    session = factory()
    project = ProjectModel(name="projeto", root_path=str(tmp_path))
    session.add(project)
    session.commit()

    marker = tmp_path / "resultado.txt"
    script = tmp_path / "deterministico.sh"
    script.write_text(f"#!/bin/sh\necho pronto > {marker}\n", encoding="utf-8")
    script.chmod(0o755)

    automation = AutomationService(session).create(
        AutomationDefinition(
            name="script determinístico",
            project_id=str(project.id),
            trigger=TriggerSpec(kind=TriggerKind.INTERVAL, interval_seconds=3600),
            action=ScriptAction(kind="script", command=[str(script)]),
            permissions=PermissionSpec(allow_scripts=True, allowed_commands=[str(script)]),
            state="enabled",
        )
    )
    automation.last_run_at = datetime.now(timezone.utc) - timedelta(seconds=7200)
    session.commit()

    # Nenhum provedor é configurado: um script não pode depender do modelo.
    supervisor = AutomationSupervisor(get_settings(), session_factory=factory)
    summary = asyncio.run(supervisor.tick())
    assert summary["executed"]
    assert marker.read_text().strip() == "pronto"
    session.close()
    engine.dispose()
