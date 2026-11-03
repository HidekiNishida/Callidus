"""
Arquivo: tests/test_autonomous_focus.py
Nome: test_autonomous_focus.py
Propósito: verificar que o worker autônomo avança uma run por vez — a mais recente — e que uma run ociosa cede a vez.
Responsabilidade: camada de testes — política de foco do worker (`focused_run`, registro do desfecho) e o tique do laço.
Componentes: focused_run, _note_outcome, autonomous_loop com escalonador falso.
Dependências: agent.services.autonomous_worker, agent.services.agent_scheduler, agent.persistence, pytest.
Observações: relógio injetado e banco temporário do pytest; nenhuma inferência nem rede.
"""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from agent.persistence.models import ExecutionRunModel
from agent.services import autonomous_worker
from agent.services.agent_scheduler import OperationResult
from agent.services.autonomous_worker import IDLE_BACKOFF_SEC, _note_outcome, focused_run

T0 = datetime(2026, 11, 3, 15, 0, tzinfo=UTC)


def _run(minutes: int, *, autonomous: bool = True) -> ExecutionRunModel:
    """Run ativa criada `minutes` depois de T0."""
    return ExecutionRunModel(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        root_task_id=uuid.uuid4(),
        status="active",
        config_json={"autonomous": autonomous},
        created_at=T0 + timedelta(minutes=minutes),
    )


def _result(run, action: str, ok: bool = True) -> OperationResult:
    """Desfecho de um passo de run, como o escalonador devolve."""
    return OperationResult(operation_id="x", kind="run_step", key=f"run:{run.id}", ok=ok, action=action)


def test_only_the_most_recent_autonomous_run_is_stepped():
    """Regressão: todas as runs ativas andavam em rodízio e a mensagem nova parecia parada."""
    old, manual, newest = _run(0), _run(30, autonomous=False), _run(10)
    assert focused_run([old, manual, newest], {}, now=100.0) is newest


def test_an_idle_run_yields_to_the_next_and_gets_its_turn_back():
    """Passo sem avanço: a run em foco cede a vez; depois do intervalo, volta a ser a escolhida."""
    old, newest = _run(0), _run(10)
    idle: dict[str, float] = {}
    _note_outcome(idle, _result(newest, "noop"), now=100.0)

    assert focused_run([old, newest], idle, now=101.0) is old
    assert focused_run([old, newest], idle, now=100.0 + IDLE_BACKOFF_SEC) is newest


def test_progress_clears_the_idle_mark_and_failures_set_it():
    """Avanço limpa a marca de ociosidade; erro do passo conta como ociosidade."""
    run = _run(0)
    idle: dict[str, float] = {}
    _note_outcome(idle, _result(run, "step_error", ok=False), now=5.0)
    assert idle == {str(run.id): 5.0}
    _note_outcome(idle, _result(run, "started_running"), now=6.0)
    assert idle == {}


def test_when_every_run_is_idle_the_newest_still_goes_first():
    """Todas ociosas: nenhuma fica sem chance; a mais recente segue na frente."""
    old, newest = _run(0), _run(10)
    idle = {str(old.id): 100.0, str(newest.id): 100.0}
    assert focused_run([old, newest], idle, now=101.0) is newest


def test_no_autonomous_run_means_nothing_to_step():
    """Sem run autônoma, o worker não submete passo."""
    assert focused_run([_run(0, autonomous=False)], {}, now=0.0) is None


class _Recorder:
    """Escalonador falso: guarda as submissões e encerra o laço no primeiro tique."""

    def __init__(self):
        """Começa sem submissões."""
        self.submitted: list[tuple[str, int]] = []

    def submit(self, kind, key, payload=None, *, priority=0):
        """Registra a submissão."""
        self.submitted.append((key, priority))
        return True

    async def run_once(self):
        """Encerra o laço depois deste tique."""
        autonomous_worker.request_stop()
        return None


def test_loop_submits_only_the_focused_run(monkeypatch):
    """O tique do laço submete só a run mais recente, com prioridade sobre o que já estava na fila."""
    captured = []

    class _Session:
        def scalars(self, stmt):
            class _Rows:
                def all(self_inner):
                    return captured.pop(0) if captured else []

            return _Rows()

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    old, newest = _run(0), _run(10)
    captured.extend([[old, newest], []])
    monkeypatch.setattr(autonomous_worker, "create_db_engine", lambda settings: None)
    monkeypatch.setattr(autonomous_worker, "build_session_factory", lambda engine: _Session)
    autonomous_worker._stop.clear()
    recorder = _Recorder()
    asyncio.run(autonomous_worker.autonomous_loop(interval_sec=0, scheduler=recorder, clock=lambda: 0.0))
    autonomous_worker._stop.clear()

    assert recorder.submitted == [(f"run:{newest.id}", 1)]
