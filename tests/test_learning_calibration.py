"""
Arquivo: tests/test_learning_calibration.py
Nome: test_learning_calibration.py
Propósito: testar a calibração adaptativa campeão/desafiador com rollback.
Responsabilidade: camada de testes — registro de mudanças, avaliação do desafiador
contra o campeão, decisão de promover/reverter/manter/bloquear, histórico e rollback.
Componentes: CalibrationChange, CalibrationRecord, CalibrationMetrics,
CalibrationStore, CalibrationEngine, register_change, evaluate, rollback, history.
Dependências: agent.learning.calibration, pytest.
Observações: usa banco temporário para isolamento; nenhum modelo real é invocado.
"""

import tempfile
import os

import pytest

from agent.learning.calibration import (
    CalibrationDecision,
    CalibrationEngine,
    CalibrationMetrics,
    CalibrationStore,
    create_calibration_engine,
    create_calibration_store,
)


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    os.unlink(db_path)


@pytest.fixture
def engine(temp_db):
    return create_calibration_engine(create_calibration_store(temp_db))


def _metrics(success_rate=0.9, tokens=1000, calls=10, duration=5000, false_complete=0.05, recovery=0):
    return CalibrationMetrics(
        success_rate=success_rate,
        tokens_per_task=tokens,
        calls_per_task=calls,
        duration_ms=duration,
        false_completion_rate=false_complete,
        recovery_count=recovery,
    )


def test_register_change_persiste(engine):
    """Registrar uma mudança a guarda no armazenamento e a deixa ativa."""
    change = engine.register_change(
        work_type="implementacao",
        parameter="context_budget",
        previous_value=8192,
        new_value=12000,
        origin="experimento",
        justification="mais contexto para arquivos grandes",
        hypothesis="reduz replanejamentos sem perder qualidade",
        scenario="funcional",
    )
    assert change.active is True
    stored = engine._store.get_change(change.id)
    assert stored is not None
    assert stored.new_value == 12000


def test_evaluate_promove_quando_melhora_sem_regressao(engine):
    """Desafiador com taxa de sucesso igual, menos tokens e menos tempo é promovido."""
    change = engine.register_change(
        work_type="implementacao",
        parameter="context_budget",
        previous_value=8192,
        new_value=12000,
        origin="experimento",
        justification="j",
        hypothesis="h",
    )
    record = engine.evaluate(
        change_id=change.id,
        champion=_metrics(success_rate=0.90, tokens=1000, duration=5000),
        challenger=_metrics(success_rate=0.90, tokens=800, duration=4000),
        samples=5,
    )
    assert record.decision == CalibrationDecision.PROMOTE
    assert record.confidence > 0
    assert record.improvement > 0
    assert record.regression is False


def test_evaluate_reverte_quando_regressao(engine):
    """Taxa de sucesso menor do desafiador causa reversão (qualidade preservada)."""
    change = engine.register_change(
        work_type="implementacao",
        parameter="max_attempts",
        previous_value=3,
        new_value=1,
        origin="experimento",
        justification="j",
        hypothesis="h",
    )
    record = engine.evaluate(
        change_id=change.id,
        champion=_metrics(success_rate=0.90),
        challenger=_metrics(success_rate=0.70),
        samples=5,
    )
    assert record.decision == CalibrationDecision.REVERT
    assert record.regression is True


def test_evaluate_mantem_com_poucas_amostras(engine):
    """Dados insuficientes não promovem nem revertem (mantém o campeão)."""
    change = engine.register_change(
        work_type="consulta",
        parameter="output_reserve",
        previous_value=512,
        new_value=256,
        origin="manual",
        justification="j",
        hypothesis="h",
    )
    record = engine.evaluate(
        change_id=change.id,
        champion=_metrics(success_rate=0.90),
        challenger=_metrics(success_rate=0.90),
        samples=1,
    )
    assert record.decision == CalibrationDecision.KEEP


def test_evaluate_bloqueia_parametro_critico_manual(engine):
    """Parâmetro crítico alterado manualmente é bloqueado (segurança preservada)."""
    change = engine.register_change(
        work_type="implementacao",
        parameter="max_tool_calls",
        previous_value=8,
        new_value=100,
        origin="manual",
        justification="mais ferramentas",
        hypothesis="h",
    )
    record = engine.evaluate(
        change_id=change.id,
        champion=_metrics(success_rate=0.90),
        challenger=_metrics(success_rate=0.90),
        samples=5,
    )
    assert record.decision == CalibrationDecision.BLOCKED


def test_rollback_desativa_mudanca(engine):
    """O rollback desativa a mudança e registra a decisão de reverter."""
    change = engine.register_change(
        work_type="implementacao",
        parameter="context_budget",
        previous_value=8192,
        new_value=12000,
        origin="experimento",
        justification="j",
        hypothesis="h",
    )
    assert engine._store.get_change(change.id).active is True
    assert engine.rollback(change.id) is True
    assert engine._store.get_change(change.id).active is False


def test_rollback_inexistente_retorna_falso(engine):
    """Rollback de mudança desconhecida retorna False."""
    assert engine.rollback("nao-existe") is False


def test_history_retorna_mudanças_e_registros(engine):
    """O histórico lista mudanças registradas e seus registros de decisão."""
    change = engine.register_change(
        work_type="implementacao",
        parameter="context_budget",
        previous_value=8192,
        new_value=12000,
        origin="experimento",
        justification="j",
        hypothesis="h",
    )
    engine.evaluate(
        change_id=change.id,
        champion=_metrics(success_rate=0.90),
        challenger=_metrics(success_rate=0.90),
        samples=5,
    )
    hist = engine.history()
    assert len(hist["changes"]) == 1
    assert len(hist["records"]) == 1
    assert hist["records"][0]["change_id"] == change.id
    hist_t = engine.history(work_type="consulta")
    assert len(hist_t["changes"]) == 0
