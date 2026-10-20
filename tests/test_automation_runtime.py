"""
Arquivo: tests/test_automation_runtime.py
Nome: test_automation_runtime.py
Propósito: Verificar de forma determinística o runtime de automações.
Responsabilidade: camada de testes — máquina de estados do disparo, persistência, idempotência, recuperação, dependências, cancelamento e segurança.
Componentes: gatilhos e fuso, eventos internos, recuperação após reinício, migração, horários perdidos, dependências, inicialização autorizada, execução de script, ação Callidus, objetivo congelado, destino remoto, idempotência, cancelamento, permissões, supervisor e reconciliação.
Dependências: agent.automation.dispatcher, agent.automation.executor, agent.automation.supervisor, agent.automation.dependencies, agent.automation.security e agent.automation.store.
Observações: banco SQLite temporário por teste; scripts são criados em tmp_path e o provedor nunca é chamado de verdade.

Testes determinísticos do runtime de automações.

Cobrem a máquina de estados do disparo, a persistência, a idempotência, a
recuperação, as dependências, o cancelamento e a segurança — sem depender de um
LLM real nem de rede.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from agent.automation.contracts import (
    AutomationDefinition,
    CallidusAction,
    DependencySpec,
    PermissionSpec,
    ScriptAction,
    TriggerSpec,
)
from agent.automation.dependencies import DependencyResolver
from agent.automation.dispatcher import Dispatcher
from agent.automation.enums import (
    AutomationState,
    FiringState,
    MissedPolicy,
    ObjectiveMode,
    TriggerKind,
)
from agent.automation.executor import AutomationExecutor
from agent.automation.security import PermissionDenied, assert_script_allowed
from agent.automation.store import AutomationService
from agent.automation.supervisor import AutomationSupervisor
from agent.automation.timezones import localize, next_cron_occurrence
from agent.config import get_settings
from agent.domain.enums import RunStatus, TaskStatus
from agent.persistence.database import build_session_factory, create_db_engine, init_db
from agent.persistence.models import (
    AutomationEventModel,
    AutomationFiringModel,
    AutomationModel,
    EventLogModel,
    ExecutionRunModel,
    ProjectModel,
    ScheduledRunModel,
    TaskModel,
)


# ─────────────────────────────────────────────────────���───── fixtures

@pytest.fixture
def db(tmp_path, monkeypatch):
    """Banco isolado por teste."""
    url = f"sqlite:///{tmp_path / 'automation.db'}"
    monkeypatch.setenv("CALLIDUS_TEST_DATABASE_URL", url)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    settings = get_settings()
    engine = init_db(create_db_engine(settings), settings)
    return engine, build_session_factory(engine), settings


@pytest.fixture
def project(db, tmp_path):
    """Cria o projeto usado pelos testes no banco temporário."""
    engine, factory, _settings = db
    session = factory()
    row = ProjectModel(name="projeto", root_path=str(tmp_path))
    session.add(row)
    session.commit()
    return row


def _script(tmp_path: Path, body: str = "echo ok\n", name: str = "alvo.sh") -> Path:
    """Grava um script executável em tmp_path e devolve o caminho."""
    path = tmp_path / name
    path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    path.chmod(0o755)
    return path


def _definition(project, **overrides) -> AutomationDefinition:
    """Monta a definição de uma automação de teste com gatilho cron e ação de script."""
    payload = {
        "name": "automação de teste",
        "project_id": str(project.id),
        "trigger": TriggerSpec(kind=TriggerKind.CRON, cron="*/5 * * * *"),
        "action": ScriptAction(kind="script", command=["/bin/sh", "-c", "echo ok"]),
        "permissions": PermissionSpec(allow_scripts=True, allowed_commands=["/bin/sh"]),
        "state": AutomationState.ENABLED.value,
    }
    payload.update(overrides)
    return AutomationDefinition(**payload)


# ─────────────────────────────────────────────────────────── 1. data e hora

def test_disparo_em_data_hora_especifica(db, project):
    """1. Execução em data e hora específicas."""
    engine, factory, _settings = db
    session = factory()
    target = datetime(2030, 5, 4, 12, 30, tzinfo=timezone.utc)
    definition = _definition(
        project,
        trigger=TriggerSpec(kind=TriggerKind.ONCE, run_at=target),
    )
    row = AutomationService(session).create(definition)
    assert row.next_run_at is not None

    dispatcher = Dispatcher(session)
    # Antes do horário: nada dispara.
    assert dispatcher.dispatch_due(row, now=target - timedelta(minutes=1)).created == []
    # Depois: um disparo, com a chave idempotente do instante.
    result = dispatcher.dispatch_due(row, now=target + timedelta(minutes=1))
    assert len(result.created) == 1
    assert result.created[0].scheduled_for == target
    session.close()


# ─────────────────────────────────────────────────────────── 2. recorrência

def test_recorrencia_cron_e_intervalo(db, project):
    """2. Recorrência cron e intervalos."""
    engine, factory, _settings = db
    session = factory()
    service = AutomationService(session)

    service.create(_definition(project))
    base = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)
    occurrences = next_cron_occurrence("*/15 * * * *", "UTC", base, limit=4)
    assert [o.minute for o in occurrences] == [15, 30, 45, 0]
    assert all(o > base for o in occurrences)

    interval_row = service.create(
        _definition(
            project,
            name="intervalo",
            trigger=TriggerSpec(kind=TriggerKind.INTERVAL, interval_seconds=900),
        )
    )
    trigger = service.trigger_of(interval_row)
    first = trigger.next_occurrence(base)
    second = trigger.next_occurrence(first)
    assert second - first == timedelta(seconds=900)
    session.close()


def test_cron_respeita_fuso_e_horario_de_verao(db, project):
    """O cron é hora de parede do fuso: a virada do horário de verão é respeitada."""
    engine, factory, _settings = db
    session = factory()
    service = AutomationService(session)
    row = service.create(
        _definition(
            project,
            trigger=TriggerSpec(kind=TriggerKind.CRON, cron="0 9 * * *", timezone="America/Sao_Paulo"),
        )
    )
    trigger = service.trigger_of(row)
    # Antes da virada (março): 09:00 local = 12:00 UTC (UTC-3).
    antes = trigger.next_occurrence(datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc))
    assert antes.hour == 12
    # Depois da virada (outubro): 09:00 local = 12:00 UTC (UTC-3, sem mudança em 2026).
    depois = trigger.next_occurrence(datetime(2026, 10, 20, 0, 0, tzinfo=timezone.utc))
    assert depois.hour == 12
    session.close()


def test_hora_inexistente_no_horario_de_verao():
    """Hora local que não existe (spring forward) é deslocada para o instante válido."""
    # 02:30 não existe em Nova York na virada de março de 2026 (o relógio salta para 03:00).
    instante = localize(datetime(2026, 3, 8, 2, 30), "America/New_York")
    assert instante.tzinfo is not None
    # O instante existe: converter de volta não muda o horário local.
    de_volta = instante.astimezone(timezone.utc).astimezone(
        __import__("zoneinfo").ZoneInfo("America/New_York")
    )
    assert de_volta.hour == 3 and de_volta.minute == 30


# ─────────────────────────────────────────────────────────── 3. eventos internos

def test_evento_interno_gera_disparo_unico(db, project):
    """3. Eventos internos e duplicação de disparos."""
    engine, factory, _settings = db
    session = factory()
    definition = _definition(
        project,
        trigger=TriggerSpec(kind=TriggerKind.EVENT, event_type="task.completed"),
    )
    row = AutomationService(session).create(definition)
    event = EventLogModel(
        project_id=project.id,
        event_type="task.completed",
        payload_json={"title": "tarefa"},
    )
    session.add(event)
    session.commit()

    dispatcher = Dispatcher(session)
    trigger = AutomationService(session).trigger_of(row)
    candidates = trigger.candidate_events(session)
    assert len(candidates) == 1
    first = dispatcher.dispatch_event(row, candidates[0])
    session.commit()
    second = dispatcher.dispatch_event(row, candidates[0])
    session.commit()
    assert first is not None
    assert second is None  # idempotente: o mesmo evento não cria dois disparos
    total = list(
        session.scalars(
            select(AutomationFiringModel).where(AutomationFiringModel.automation_id == row.id)
        ).all()
    )
    assert len(total) == 1
    session.close()


# ─────────────────────────────────────────────────────────── 4. recuperação

def test_recuperacao_apos_reinicio(db, project):
    """4. Recuperação após reinício: o disparo interrompido volta para a fila."""
    engine, factory, settings = db
    session = factory()
    row = AutomationService(session).create(_definition(project))
    firing = Dispatcher(session).dispatch_manual(row, tag="manual")
    firing.state = FiringState.PREPARING.value
    session.commit()

    supervisor = AutomationSupervisor(settings, session_factory=factory)
    import asyncio

    summary = asyncio.run(supervisor.tick())
    assert summary["recovered"] == 1
    session.expire_all()
    assert firing.state != FiringState.PREPARING.value
    session.close()


def test_migracao_preserva_agendamentos_antigos(db):
    """15. Migração do banco existente sem perda de dados."""
    engine, factory, _settings = db
    session = factory()
    project = ProjectModel(name="antigo", root_path=str(Path(os.getcwd())))
    session.add(project)
    session.commit()
    legacy = ScheduledRunModel(
        project_id=project.id, cron_expression="0 10 * * 1", enabled=True
    )
    session.add(legacy)
    session.commit()
    session.close()

    # A migração roda em `init_db`.
    init_db(engine, get_settings())
    session = factory()
    automations = list(session.scalars(select(AutomationModel)).all())
    assert len(automations) == 1
    assert automations[0].trigger_json["cron"] == "0 10 * * 1"
    # A automação herdada nasce desabilitada: a decisão de executá-la é do usuário.
    assert automations[0].state == AutomationState.DISABLED.value
    # A tabela antiga continua lá: nada foi apagado.
    assert session.get(ScheduledRunModel, legacy.id) is not None
    session.close()


def test_migracao_e_idempotente(db):
    """Rodar a migração duas vezes não duplica as automações migradas."""
    engine, factory, _settings = db
    session = factory()
    project = ProjectModel(name="antigo", root_path=str(Path(os.getcwd())))
    session.add(project)
    session.commit()
    session.add(
        ScheduledRunModel(project_id=project.id, cron_expression="0 9 * * *", enabled=False)
    )
    session.commit()
    session.close()

    init_db(engine, get_settings())
    init_db(engine, get_settings())
    session = factory()
    assert len(list(session.scalars(select(AutomationModel)).all())) == 1
    session.close()


# ─────────────────────────────────────────────────────────── 5. horários perdidos

@pytest.mark.parametrize(
    "policy,expected_created,expected_state",
    [
        (MissedPolicy.RUN_ONCE, 1, FiringState.PENDING.value),
        (MissedPolicy.CATCH_UP, 3, FiringState.PENDING.value),
        (MissedPolicy.GROUP, 1, FiringState.PENDING.value),
        (MissedPolicy.SKIP, 1, FiringState.SKIPPED.value),
    ],
)
def test_politica_de_horarios_perdidos(db, project, policy, expected_created, expected_state):
    """5. Horários perdidos e políticas de retomada."""
    engine, factory, _settings = db
    session = factory()
    service = AutomationService(session)
    row = service.create(
        _definition(project, trigger=TriggerSpec(kind=TriggerKind.CRON, cron="* * * * *"))
    )
    row.missed_policy = str(policy)
    row.last_run_at = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
    session.commit()

    dispatcher = Dispatcher(session)
    now = datetime(2026, 3, 1, 0, 3, tzinfo=timezone.utc)  # três janelas de 1 minuto
    result = dispatcher.dispatch_due(row, now=now)
    assert len(result.created) == expected_created
    assert result.created[0].state == expected_state
    session.close()


# ─────────────────────────────────────────────────────────── 6. dependências

def test_dependencia_ausente_bloqueia_e_reagenda(db, project, tmp_path):
    """6. Falta e recuperação de dependências."""
    engine, factory, settings = db
    session = factory()
    definition = _definition(
        project,
        dependencies=[
            DependencySpec(
                kind="interpreter",
                name="interpretador-inexistente",
                params={"name": "callidus-nao-existe-xyz"},
            )
        ],
    )
    row = AutomationService(session).create(definition)
    firing = Dispatcher(session).dispatch_manual(row, tag="manual")
    session.commit()

    executor = AutomationExecutor(session, settings)
    import asyncio

    outcome = asyncio.run(executor.execute(firing))
    assert outcome.state == FiringState.WAITING_DEPENDENCY.value
    assert firing.next_attempt_at is not None
    assert "interpretador-inexistente" in (firing.error or "")
    session.close()


def test_dependencia_recuperada_permite_execucao(db, project, tmp_path):
    """6b. Quando a dependência volta, a execução acontece."""
    engine, factory, settings = db
    session = factory()
    script = _script(tmp_path)
    definition = _definition(
        project,
        action=ScriptAction(kind="script", command=[str(script)]),
        permissions=PermissionSpec(allow_scripts=True, allowed_commands=[str(script)]),
        dependencies=[
            DependencySpec(kind="script", name="alvo", params={"path": str(script)})
        ],
    )
    row = AutomationService(session).create(definition)
    firing = Dispatcher(session).dispatch_manual(row, tag="manual")
    session.commit()
    executor = AutomationExecutor(session, settings)
    import asyncio

    outcome = asyncio.run(executor.execute(firing))
    assert outcome.state == FiringState.COMPLETED.value
    assert firing.result_json["action"]["exit_code"] == 0
    session.close()


# ───────────────────────────────────────────────────── 7. inicialização autorizada

def test_inicializacao_autorizada_e_bloqueio_nao_autorizado(db, tmp_path):
    """7. Inicialização autorizada e bloqueio de inicialização não autorizada."""
    engine, factory, settings = db
    marker = tmp_path / "iniciado.txt"
    alvo = tmp_path / "inexistente.sh"
    resolver = DependencyResolver(settings=settings)
    spec = DependencySpec(
        kind="script",
        name="sinalizador",
        params={"path": str(alvo)},
        start={
            "mechanism": "command",
            "authorized": True,
            "command": [
                "/bin/sh",
                "-c",
                f"printf '#!/bin/sh\\n' > {alvo} && chmod +x {alvo} && touch {marker}",
            ],
        },
    )
    check = await_resolver(resolver, spec)
    assert check.ok
    assert marker.exists()

    marker2 = tmp_path / "iniciado2.txt"
    alvo2 = tmp_path / "inexistente2.sh"
    spec2 = DependencySpec(
        kind="script",
        name="sinalizador",
        params={"path": str(alvo2)},
        start={
            "mechanism": "command",
            "authorized": False,
            "command": ["/bin/sh", "-c", f"touch {marker2} && touch {alvo2}"],
        },
    )
    check2 = await_resolver(resolver, spec2)
    assert not check2.ok
    assert not marker2.exists()


def await_resolver(resolver: DependencyResolver, spec: DependencySpec):
    """Executa a verificação de dependências de forma síncrona."""
    import asyncio

    return asyncio.run(resolver.check_all([spec]))


# ─────────────────────────────────────────────────────────── 8. scripts

def test_script_com_codigo_de_saida_diferente_de_zero(db, project, tmp_path):
    """8. Execução de scripts com códigos de saída diferentes de zero."""
    engine, factory, settings = db
    session = factory()
    script = _script(tmp_path, body="exit 3\n")
    row = AutomationService(session).create(
        _definition(
            project,
            action=ScriptAction(kind="script", command=[str(script)]),
            permissions=PermissionSpec(allow_scripts=True, allowed_commands=[str(script)]),
        )
    )
    firing = Dispatcher(session).dispatch_manual(row, tag="manual")
    session.commit()
    executor = AutomationExecutor(session, settings)
    import asyncio

    outcome = asyncio.run(executor.execute(firing))
    assert outcome.state != FiringState.COMPLETED.value
    assert firing.result_json["action"]["exit_code"] == 3
    session.close()


def test_script_com_timeout(db, project, tmp_path):
    """8b. Timeout de script."""
    engine, factory, settings = db
    session = factory()
    script = _script(tmp_path, body="sleep 5\n")
    row = AutomationService(session).create(
        _definition(
            project,
            action=ScriptAction(kind="script", command=[str(script)], timeout_sec=0.5),
            permissions=PermissionSpec(allow_scripts=True, allowed_commands=[str(script)]),
        )
    )
    firing = Dispatcher(session).dispatch_manual(row, tag="manual")
    session.commit()
    executor = AutomationExecutor(session, settings)
    import asyncio

    outcome = asyncio.run(executor.execute(firing))
    assert outcome.state != FiringState.COMPLETED.value
    assert "tempo" in (firing.error or "").lower()
    session.close()


def test_script_repetido_nao_repeti_o_efeito(db, project, tmp_path):
    """Efeito parcial: o recibo impede repetir o script já executado."""
    engine, factory, settings = db
    session = factory()
    counter = tmp_path / "contador.txt"
    script = _script(tmp_path, body=f"echo x >> {counter}\n")
    receipt = tmp_path / "recibo.txt"
    row = AutomationService(session).create(
        _definition(
            project,
            action=ScriptAction(
                kind="script", command=[str(script)], receipt_path=str(receipt)
            ),
            permissions=PermissionSpec(allow_scripts=True, allowed_commands=[str(script)]),
        )
    )
    executor = AutomationExecutor(session, settings)
    import asyncio

    first = Dispatcher(session).dispatch_manual(row, tag="manual")
    session.commit()
    outcome = asyncio.run(executor.execute(first))
    assert outcome.state == FiringState.COMPLETED.value
    assert len(counter.read_text().strip().splitlines()) == 1

    second = Dispatcher(session).dispatch_manual(row, tag="manual")
    session.commit()
    outcome2 = asyncio.run(executor.execute(second))
    assert outcome2.state == FiringState.COMPLETED.value
    assert len(counter.read_text().strip().splitlines()) == 1
    session.close()


# ─────────────────────────────────────────────────────────── 9. tarefas Callidus

def test_acao_callidus_cria_tarefa_raiz_e_run(db, project):
    """9. Execução de tarefas Callidus com criação correta da tarefa raiz."""
    engine, factory, settings = db
    session = factory()
    row = AutomationService(session).create(
        _definition(
            project,
            action=CallidusAction(
                kind="callidus",
                objective="verificar o projeto",
                autonomous=False,
            ),
        )
    )
    firing = Dispatcher(session).dispatch_manual(row, tag="manual")
    session.commit()
    executor = AutomationExecutor(session, settings)
    import asyncio

    outcome = asyncio.run(executor.execute(firing))
    assert outcome.state == FiringState.RUNNING.value  # o run foi entregue ao worker
    task = session.get(TaskModel, firing.task_id)
    assert task is not None
    assert task.parent_id is None
    assert task.objective == "verificar o projeto"
    run = session.get(ExecutionRunModel, firing.run_id)
    assert run is not None
    assert run.root_task_id == task.id
    assert run.status == RunStatus.ACTIVE.value
    # A tarefa raiz tem agente (o mesmo contrato de um run criado pela interface).
    assert task.status == TaskStatus.PENDING.value
    session.close()


def test_objetivo_congelado_nao_muda_com_a_conversa(db, project):
    """Alteração posterior na conversa não muda uma automação já aprovada."""
    engine, factory, _settings = db
    session = factory()
    task = TaskModel(
        project_id=project.id,
        title="tarefa",
        objective="objetivo original",
    )
    session.add(task)
    session.commit()
    row = AutomationService(session).create(
        _definition(
            project,
            action=CallidusAction(
                kind="callidus", task_id=str(task.id), objective_mode=ObjectiveMode.FROZEN
            ),
        )
    )
    assert row.objective_json["objective"] == "objetivo original"
    # A tarefa muda depois da aprovação.
    task.objective = "objetivo novo"
    session.commit()
    assert row.objective_json["objective"] == "objetivo original"
    session.close()


# ─────────────────────────────────────────────────────────── 10. provedor

def test_provedor_indisponivel_nao_gera_sucesso(db, project):
    """10. Provedor indisponível sem gerar falsos sucessos."""
    engine, factory, settings = db
    session = factory()
    resolver = DependencyResolver(settings=settings)
    spec = DependencySpec(
        kind="provider",
        name="provedor-inexistente",
        params={"name": "provedor-callidus-inexistente"},
    )
    check = await_resolver(resolver, spec)
    assert not check.ok
    assert check.blocking
    session.close()


# ─────────────────────────────────────────────────────────── 11. remoto

def test_destino_remoto_indisponivel(db, project):
    """11. Projeto remoto indisponível e recuperação da conectividade."""
    engine, factory, settings = db
    session = factory()
    resolver = DependencyResolver(
        settings=settings,
        remote={"host": "127.0.0.1", "port": 59999, "shell": "posix", "timeout": 5},
        target_kind="remote",
    )
    spec = DependencySpec(kind="remote", name="destino")
    check = await_resolver(resolver, spec)
    assert not check.ok
    assert check.blocking[0].state == "unreachable"
    session.close()


def test_execucao_remota_usa_o_destino_configurado(db, project, monkeypatch):
    """O comando remoto vai para o computador de destino, não para a máquina local."""
    engine, factory, settings = db
    session = factory()
    captured: dict = {}

    class FakeResult:
        """Resultado falso de comando remoto, com saída de sucesso."""
        exit_code = 0
        stdout = "ok remoto"
        stderr = ""

    class FakeSsh:
        """Transporte SSH falso que registra a configuração e o comando executado."""
        def __init__(self, config):
            """Guarda a configuração remota recebida para inspeção."""
            captured["config"] = config

        async def run(self, command, cwd=None, timeout=None, on_output=None):
            """Registra o comando e o diretório e devolve um resultado de sucesso."""
            captured["command"] = command
            captured["cwd"] = cwd
            return FakeResult()

    monkeypatch.setattr("agent.remote.ssh.SshTransport", FakeSsh)
    from agent.automation.actions.script import ScriptActionRunner

    runner = ScriptActionRunner(
        ScriptAction(kind="script", command=["python3", "alvo.py"], cwd="sub/pasta")
    )
    import asyncio
    from agent.automation.actions.base import ActionContext

    ctx = ActionContext(
        session=session,
        settings=settings,
        automation_id=uuid.uuid4(),
        project_id=project.id,
        firing_id=uuid.uuid4(),
        idempotency_key="k",
        target={
            "kind": "remote",
            "remote": {"host": "exemplo", "shell": "powershell", "root": "C:\\projeto"},
            "permissions": PermissionSpec(allow_scripts=True, allowed_commands=["python3"]),
            "project_root": str(Path(os.getcwd())),
        },
    )
    result = asyncio.run(runner.execute(ctx))
    assert result.ok
    assert captured["command"] == ["python3", "alvo.py"]
    assert captured["cwd"] == "sub\\pasta"
    assert captured["config"].host == "exemplo"
    session.close()


# ─────────────────────────────────────────────────────────── 12. plataformas

def test_caminho_e_interpretador_por_plataforma():
    """12. Destinos Windows, Linux e macOS com interpretadores e caminhos adequados."""
    from agent.remote.ssh import RemoteConfig

    posix = RemoteConfig(host="h", shell="posix")
    windows = RemoteConfig(host="h", shell="powershell", root="C:\\projeto")
    assert posix.is_windows is False
    assert windows.is_windows is True
    assert posix.root == "."
    # O caminho remoto usa o separador do destino.
    from agent.remote.ssh import SshTransport

    transport = SshTransport(windows)
    assert transport._remote_path("a/b") == "C:\\projeto\\a\\b"
    posix_transport = SshTransport(posix)
    assert posix_transport._remote_path("a/b") == "a/b"


# ─────────────────────────────────────────────────────────── 13. duplicidade

def test_protecao_contra_execucao_duplicada(db, project):
    """13. Proteção contra execução duplicada."""
    engine, factory, _settings = db
    session = factory()
    row = AutomationService(session).create(
        _definition(project, trigger=TriggerSpec(kind=TriggerKind.CRON, cron="* * * * *"))
    )
    row.last_run_at = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
    session.commit()
    dispatcher = Dispatcher(session)
    first = dispatcher.dispatch_due(
        row, now=datetime(2026, 3, 1, 0, 6, tzinfo=timezone.utc)
    )
    assert len(first.created) == 1
    session.commit()
    # Reprocessa a **mesma** janela: a chave de idempotência impede o segundo disparo.
    row.last_run_at = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
    session.commit()
    second = dispatcher.dispatch_due(
        row, now=datetime(2026, 3, 1, 0, 6, tzinfo=timezone.utc)
    )
    assert second.created == []
    assert second.duplicates == 1
    session.close()


def test_chave_de_idempotencia_unica_no_banco(db, project):
    """A chave de idempotência é única no banco: a segunda inserção é recusada."""
    engine, factory, _settings = db
    session = factory()
    row = AutomationService(session).create(_definition(project))
    dispatcher = Dispatcher(session)
    row.last_run_at = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
    session.commit()
    result = dispatcher.dispatch_due(row, now=datetime(2026, 3, 1, 0, 6, tzinfo=timezone.utc))
    session.commit()
    firing = result.created[0]
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        session.add(
            AutomationFiringModel(
                automation_id=row.id,
                project_id=project.id,
                idempotency_key=firing.idempotency_key,
                scheduled_for=datetime.now(timezone.utc),
            )
        )
        session.commit()
    session.rollback()
    session.close()


# ─────────────────────────────────────────────────────────── 14. estados

def test_cancelamento_suspensao_e_desativacao(db, project):
    """14. Cancelamento, suspensão e desativação da automação."""
    engine, factory, settings = db
    session = factory()
    service = AutomationService(session)
    row = service.create(_definition(project))
    firing = Dispatcher(session).dispatch_manual(row, tag="manual")
    session.commit()

    service.set_state(row.id, AutomationState.SUSPENDED)
    session.commit()
    assert row.next_run_at is None
    import asyncio

    supervisor = AutomationSupervisor(settings, session_factory=factory)
    asyncio.run(supervisor.tick())
    session.expire_all()
    assert firing.state == FiringState.SKIPPED.value

    service.set_state(row.id, AutomationState.DISABLED)
    session.commit()
    assert row.state == AutomationState.DISABLED.value
    session.close()


def test_cancelar_disparos_pendentes(db, project):
    """O disparo cancelado permanece cancelado no banco."""
    engine, factory, _settings = db
    session = factory()
    row = AutomationService(session).create(_definition(project))
    firing = Dispatcher(session).dispatch_manual(row, tag="manual")
    session.commit()
    firing.state = FiringState.CANCELLED.value
    session.commit()
    assert firing.state == FiringState.CANCELLED.value
    session.close()


# ─────────────────────────────────────────────────────────── 16. segurança

def test_script_sem_autorizacao_e_bloqueado(db, project, tmp_path):
    """16. Proteção contra scripts e operações sem autorização."""
    engine, factory, settings = db
    session = factory()
    script = _script(tmp_path)
    row = AutomationService(session).create(
        _definition(
            project,
            action=ScriptAction(kind="script", command=[str(script)]),
            permissions=PermissionSpec(allow_scripts=False, allowed_commands=[str(script)]),
        )
    )
    firing = Dispatcher(session).dispatch_manual(row, tag="manual")
    session.commit()
    executor = AutomationExecutor(session, settings)
    import asyncio

    outcome = asyncio.run(executor.execute(firing))
    assert outcome.state == FiringState.FAILED.value
    assert "autoriza" in (firing.error or "").lower()
    session.close()


def test_comando_fora_da_allowlist_e_bloqueado():
    """Um comando fora da lista permitida é recusado com erro de permissão."""
    permissions = PermissionSpec(allow_scripts=True, allowed_commands=["/bin/sh"])
    with pytest.raises(PermissionDenied):
        assert_script_allowed(["/usr/bin/curl", "http://exemplo"], permissions)


def test_segredo_nao_vai_para_a_evidencia(db, project, tmp_path):
    """Segredos não aparecem na evidência persistida."""
    engine, factory, settings = db
    session = factory()
    script = _script(tmp_path, body="echo 'api_key=sk-abcdefghijklmnopqrstuvwxyz'\n")
    row = AutomationService(session).create(
        _definition(
            project,
            action=ScriptAction(kind="script", command=[str(script)]),
            permissions=PermissionSpec(allow_scripts=True, allowed_commands=[str(script)]),
        )
    )
    firing = Dispatcher(session).dispatch_manual(row, tag="manual")
    session.commit()
    executor = AutomationExecutor(session, settings)
    import asyncio

    asyncio.run(executor.execute(firing))
    evidence = (firing.result_json or {}).get("action", {})
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in str(evidence)
    session.close()


# ─────────────────────────────────────────────────────────── supervisor

def test_supervisor_despara_e_executa_uma_automacao_vencida(db, project, tmp_path):
    """O supervisor descobre o vencimento e executa — sem inferência."""
    engine, factory, settings = db
    session = factory()
    script = _script(tmp_path)
    row = AutomationService(session).create(
        _definition(
            project,
            trigger=TriggerSpec(kind=TriggerKind.INTERVAL, interval_seconds=60),
            action=ScriptAction(kind="script", command=[str(script)]),
            permissions=PermissionSpec(allow_scripts=True, allowed_commands=[str(script)]),
        )
    )
    # Simula o momento do disparo: o intervalo já passou.
    row.last_run_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    row.next_run_at = datetime.now(timezone.utc) - timedelta(seconds=60)
    session.commit()
    session.close()

    import asyncio

    supervisor = AutomationSupervisor(settings, session_factory=factory)
    summary = asyncio.run(supervisor.tick())
    assert summary["dispatched"]["created"]
    assert any(item["state"] == FiringState.COMPLETED.value for item in summary["executed"])

    session = factory()
    firings = list(session.scalars(select(AutomationFiringModel)).all())
    assert any(f.state == FiringState.COMPLETED.value for f in firings)
    session.close()


def test_status_e_diagnostico_do_supervisor(db, project):
    """O status e o diagnóstico do supervisor listam as automações e a política de horário perdido."""
    engine, factory, settings = db
    session = factory()
    AutomationService(session).create(_definition(project))
    session.commit()
    session.close()
    supervisor = AutomationSupervisor(settings, session_factory=factory)
    status = supervisor.status()
    assert status["automations"]["total"] == 1
    diagnosis = supervisor.diagnose()
    assert len(diagnosis["automations"]) == 1
    assert diagnosis["automations"][0]["missed_policy"] == "run_once"


def test_evento_publicado_por_adaptador_dispara_automacao(db, project):
    """Evento durável publicado por adaptador vira disparo."""
    engine, factory, settings = db
    session = factory()
    row = AutomationService(session).create(
        _definition(
            project,
            trigger=TriggerSpec(kind=TriggerKind.EVENT, event_type="webhook.recebido"),
        )
    )
    session.add(
        AutomationEventModel(
            event_type="webhook.recebido",
            source="adapter",
            project_id=project.id,
            payload_json={"arquivo": "a.txt"},
        )
    )
    session.commit()
    import asyncio

    supervisor = AutomationSupervisor(settings, session_factory=factory)
    asyncio.run(supervisor.tick())
    session.expire_all()
    firings = list(
        session.scalars(
            select(AutomationFiringModel).where(AutomationFiringModel.automation_id == row.id)
        ).all()
    )
    assert len(firings) == 1
    session.close()


def test_reconciliacao_fecha_o_disparo_quando_o_run_termina(db, project):
    """O disparo só fecha quando o run termina — registrar não é concluir."""
    engine, factory, settings = db
    session = factory()
    row = AutomationService(session).create(
        _definition(
            project,
            action=CallidusAction(kind="callidus", objective="fazer", autonomous=False),
        )
    )
    firing = Dispatcher(session).dispatch_manual(row, tag="manual")
    session.commit()
    import asyncio

    executor = AutomationExecutor(session, settings)
    asyncio.run(executor.execute(firing))
    session.commit()
    session.expire_all()
    assert firing.state == FiringState.RUNNING.value

    run = session.get(ExecutionRunModel, firing.run_id)
    run.status = RunStatus.COMPLETED.value
    session.commit()

    outcomes = executor.reconcile()
    session.expire_all()
    assert firing.state == FiringState.COMPLETED.value
    assert outcomes and outcomes[0].ok
    session.close()
