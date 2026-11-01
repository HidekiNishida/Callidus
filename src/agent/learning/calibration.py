"""
Arquivo: src/agent/learning/calibration.py
Nome: calibration.py
Propósito: calibração adaptativa campeão/desafiador com rollback e histórico persistido.
Responsabilidade: camada de aplicação — registra mudanças de configuração (identificador,
valores anterior/novo, origem, versão, justificativa, limites), executa experimentos
controlados (uma variável ou conjunto pequeno relacionado), compara desafiador com o
campeão, promove apenas com melhoria real sem regressão de qualidade ou segurança, e
permite reverter ao último perfil confiável.
Componentes: CalibrationChange, CalibrationRecord, CalibrationDecision,
CalibrationStore, CalibrationEngine.
Dependências: agent.learning.profiles (ProfileLimit), agent.intelligence.analytics,
sqlite3, uuid, datetime, dataclasses, typing.
Observações: aprendizado operacional apenas — nunca altera código-fonte, regras de
segurança ou limites globais por inferência comum; alterações são rastreáveis,
reversíveis e baseadas em evidências; não executa benchmarks pesados a cada inicialização.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agent.learning.profiles import ProfileLimit

CALIBRATION_SCHEMA_VERSION = 1
# Melhoria relativa mínima (fração) para promover o desafiador sobre o campeão.
MIN_RELATIVE_IMPROVEMENT = 0.05
# Mínimo de execuções comparáveis antes de considerar uma promoção.
MIN_SAMPLES = 3
# Confiança mínima para promover (0..1).
MIN_CONFIDENCE = 0.6


class CalibrationDecision(str):
    """Decisão de um experimento de calibração."""

    PROMOTE = "promote"      # desafiador vira o novo campeão
    REVERT = "revert"        # desafiador piorou; volta ao campeão
    KEEP = "keep"            # dados insuficientes ou sem diferença relevante; mantém campeão
    BLOCKED = "blocked"      # mudança insegura; bloqueada com diagnóstico


@dataclass(frozen=True)
class CalibrationChange:
    """Proposta de mudança de calibração."""

    id: str
    work_type: str
    parameter: str              # nome do limite (ex.: context_budget, max_attempts)
    previous_value: Any
    new_value: Any
    origin: str                 # "manual", "experimento", "diagnostico"
    justification: str
    hypothesis: str
    version: int = 1
    scenario: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    active: bool = True


@dataclass(frozen=True)
class CalibrationRecord:
    """Resultado de uma avaliação de calibração."""

    id: str
    change_id: str
    champion_metrics: dict[str, Any]
    challenger_metrics: dict[str, Any]
    decision: str
    confidence: float
    improvement: float          # melhoria relativa do desafiador sobre o campeão
    regression: bool            # houve regressão de qualidade/segurança
    samples: int
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    applied_at: str | None = None
    reverted_at: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class CalibrationMetrics:
    """Métricas comparáveis de um perfil (campeão ou desafiador)."""

    success_rate: float
    tokens_per_task: float
    calls_per_task: float
    duration_ms: float
    false_completion_rate: float
    recovery_count: int


class CalibrationStore:
    """Armazenamento persistente de mudanças e resultados de calibração."""

    def __init__(self, db_path: str) -> None:
        """Inicializa o armazenamento (tabelas adicionais, criadas se ausentes).

        Args:
            db_path: caminho do banco SQLite de calibração (arquivo novo, aditivo).
        """
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Cria as tabelas de calibração se não existirem (adiativo, sem migração)."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS calibration_changes (
                    id TEXT PRIMARY KEY,
                    work_type TEXT NOT NULL,
                    parameter TEXT NOT NULL,
                    previous_value TEXT NOT NULL,
                    new_value TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    justification TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    scenario TEXT,
                    created_at TEXT NOT NULL,
                    active INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS calibration_records (
                    id TEXT PRIMARY KEY,
                    change_id TEXT NOT NULL,
                    champion_metrics TEXT NOT NULL,
                    challenger_metrics TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    improvement REAL NOT NULL,
                    regression INTEGER NOT NULL,
                    samples INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    applied_at TEXT,
                    reverted_at TEXT,
                    reason TEXT,
                    FOREIGN KEY (change_id) REFERENCES calibration_changes(id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cal_change_work_type "
                "ON calibration_changes(work_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cal_record_change "
                "ON calibration_records(change_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cal_record_decision "
                "ON calibration_records(decision)"
            )

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def save_change(self, change: CalibrationChange) -> None:
        """Salva uma proposta de mudança de calibração."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO calibration_changes (
                    id, work_type, parameter, previous_value, new_value, origin,
                    justification, hypothesis, version, scenario, created_at, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    change.id, change.work_type, change.parameter,
                    _dump(change.previous_value), _dump(change.new_value),
                    change.origin, change.justification, change.hypothesis,
                    change.version, change.scenario, change.created_at,
                    1 if change.active else 0,
                ),
            )

    def save_record(self, record: CalibrationRecord) -> None:
        """Salva o resultado de uma avaliação de calibração."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO calibration_records (
                    id, change_id, champion_metrics, challenger_metrics, decision,
                    confidence, improvement, regression, samples, created_at,
                    applied_at, reverted_at, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id, record.change_id,
                    _dump(record.champion_metrics), _dump(record.challenger_metrics),
                    record.decision, record.confidence, record.improvement,
                    1 if record.regression else 0, record.samples, record.created_at,
                    record.applied_at, record.reverted_at, record.reason,
                ),
            )

    def get_change(self, change_id: str) -> CalibrationChange | None:
        """Devolve uma mudança pelo identificador."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM calibration_changes WHERE id = ?", (change_id,)
            ).fetchone()
        return _row_to_change(row) if row else None

    def list_changes(self, work_type: str | None = None, active: bool | None = None) -> list[CalibrationChange]:
        """Lista mudanças de calibração, opcionalmente filtradas."""
        conditions: list[str] = []
        params: list[Any] = []
        if work_type is not None:
            conditions.append("work_type = ?")
            params.append(work_type)
        if active is not None:
            conditions.append("active = ?")
            params.append(1 if active else 0)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM calibration_changes {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [_row_to_change(r) for r in rows]

    def list_records(self, change_id: str | None = None) -> list[CalibrationRecord]:
        """Lista registros de avaliação, opcionalmente filtrados por mudança."""
        params: list[Any] = []
        where = ""
        if change_id is not None:
            where = "WHERE change_id = ?"
            params.append(change_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM calibration_records {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [_row_to_record(r) for r in rows]

    def latest_decision(self, change_id: str) -> CalibrationRecord | None:
        """Devolve o último registro de decisão para uma mudança."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM calibration_records
                WHERE change_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (change_id,),
            ).fetchone()
        return _row_to_record(row) if row else None


class CalibrationEngine:
    """Motor de calibração adaptativa campeão/desafiador.

    O campeão é a configuração corrente confiável (ProfileCatalog). O desafiador é
    uma mudança candidata. O desafiador só é promovido quando mostra melhoria real
    sobre o campeão, sem regressão de qualidade ou segurança, com amostras suficientes.
    """

    def __init__(self, store: CalibrationStore) -> None:
        """Cria o motor ligado ao armazenamento de calibração.

        Args:
            store: armazenamento de mudanças e registros.
        """
        self._store = store

    def register_change(
        self,
        *,
        work_type: str,
        parameter: str,
        previous_value: Any,
        new_value: Any,
        origin: str,
        justification: str,
        hypothesis: str,
        scenario: str | None = None,
        version: int = 1,
    ) -> CalibrationChange:
        """Registra uma mudança candidata de calibração.

        Args:
            work_type: tipo de trabalho afetado.
            parameter: nome do parâmetro/limite alterado.
            previous_value: valor anterior.
            new_value: valor proposto.
            origin: origem da mudança (manual, experimento, diagnostico).
            justification: por que a mudança é proposta.
            hypothesis: hipótese de efeito (ex.: "reduz tokens sem perder qualidade").
            scenario: cenário de avaliação associado.
            version: versão da mudança.

        Returns:
            A mudança registrada.
        """
        change = CalibrationChange(
            id=str(uuid.uuid4()),
            work_type=work_type,
            parameter=parameter,
            previous_value=previous_value,
            new_value=new_value,
            origin=origin,
            justification=justification,
            hypothesis=hypothesis,
            version=version,
            scenario=scenario,
        )
        self._store.save_change(change)
        return change

    def evaluate(
        self,
        change_id: str,
        champion: CalibrationMetrics,
        challenger: CalibrationMetrics,
        samples: int,
        *,
        reason: str | None = None,
    ) -> CalibrationRecord:
        """Avalia se o desafiador deve substituir o campeão.

        Args:
            change_id: identificador da mudança candidata.
            champion: métricas da configuração corrente.
            challenger: métricas da configuração candidata.
            samples: número de execuções comparáveis usadas.
            reason: justificativa livre da decisão.

        Returns:
            O registro de decisão (promover, reverter, manter ou bloquear).
        """
        change = self._store.get_change(change_id)
        if change is None or not change.active:
            record = CalibrationRecord(
                id=str(uuid.uuid4()),
                change_id=change_id,
                champion_metrics=_metrics_to_dict(champion),
                challenger_metrics=_metrics_to_dict(challenger),
                decision=CalibrationDecision.BLOCKED,
                confidence=0.0,
                improvement=0.0,
                regression=False,
                samples=samples,
                reason="mudança não encontrada ou inativa",
            )
            self._store.save_record(record)
            return record

        # Segurança: nunca promove uma mudança que afete parâmetros críticos de
        # segurança sem revisão explícita (origin != "diagnostico" sem justificativa).
        critical = {"max_attempts", "max_tool_calls", "max_tool_iterations"}
        if change.parameter in critical and change.origin == "manual":
            record = CalibrationRecord(
                id=str(uuid.uuid4()),
                change_id=change_id,
                champion_metrics=_metrics_to_dict(champion),
                challenger_metrics=_metrics_to_dict(challenger),
                decision=CalibrationDecision.BLOCKED,
                confidence=1.0,
                improvement=0.0,
                regression=False,
                samples=samples,
                reason=f"parâmetro crítico {change.parameter} requer revisão de segurança",
            )
            self._store.save_record(record)
            return record

        # Dados insuficientes: mantém o campeão.
        if samples < MIN_SAMPLES:
            decision = CalibrationDecision.KEEP
            confidence = 0.0
            improvement = _relative_improvement(champion, challenger)
            regression = _has_regression(champion, challenger)
            reason = reason or "dados insuficientes para promover"
        else:
            improvement = _relative_improvement(champion, challenger)
            regression = _has_regression(champion, challenger)
            # Confiança baseada em amostras e ausência de regressão.
            confidence = min(0.95, 0.5 + 0.1 * samples) * (0.0 if regression else 1.0)
            if regression:
                decision = CalibrationDecision.REVERT
            elif improvement >= MIN_RELATIVE_IMPROVEMENT and confidence >= MIN_CONFIDENCE:
                decision = CalibrationDecision.PROMOTE
            else:
                decision = CalibrationDecision.KEEP
            reason = reason or (
                f"melhoria relativa {improvement:.1%}, regressao={regression}, "
                f"amostras={samples}"
            )

        record = CalibrationRecord(
            id=str(uuid.uuid4()),
            change_id=change_id,
            champion_metrics=_metrics_to_dict(champion),
            challenger_metrics=_metrics_to_dict(challenger),
            decision=decision,
            confidence=confidence,
            improvement=improvement,
            regression=regression,
            samples=samples,
            applied_at=datetime.now(UTC).isoformat() if decision == CalibrationDecision.PROMOTE else None,
            reason=reason,
        )
        self._store.save_record(record)
        return record

    def champion_config(self, work_type: str) -> ProfileLimit:
        """Devolve o limite campeão (com sobreposições de calibração aplicadas).

        Isso é delegado ao ProfileCatalog; aqui registra que o campeão é a
        configuração corrente confiável.

        Args:
            work_type: tipo de trabalho.

        Returns:
            O limite campeão para o tipo de trabalho.
        """
        # Implementado pelo ProfileCatalog; o motor apenas expõe o conceito.
        raise NotImplementedError("use ProfileCatalog.profile_for para o campeão")

    def rollback(self, change_id: str) -> bool:
        """Desativa uma mudança (rollback), voltando ao campeão anterior.

        Args:
            change_id: identificador da mudança a desativar.

        Returns:
            Verdadeiro quando a mudança existiu e foi desativada.
        """
        change = self._store.get_change(change_id)
        if change is None:
            return False
        # Marca como inativa criando uma cópia com active=False.
        inactive = CalibrationChange(
            id=change.id,
            work_type=change.work_type,
            parameter=change.parameter,
            previous_value=change.previous_value,
            new_value=change.new_value,
            origin=change.origin,
            justification=change.justification,
            hypothesis=change.hypothesis,
            version=change.version + 1,
            scenario=change.scenario,
            created_at=datetime.now(UTC).isoformat(),
            active=False,
        )
        self._store.save_change(inactive)
        # Registra a decisão de reverter.
        record = CalibrationRecord(
            id=str(uuid.uuid4()),
            change_id=change_id,
            champion_metrics={},
            challenger_metrics={},
            decision=CalibrationDecision.REVERT,
            confidence=1.0,
            improvement=0.0,
            regression=False,
            samples=0,
            reverted_at=datetime.now(UTC).isoformat(),
            reason="rollback executado",
        )
        self._store.save_record(record)
        return True

    def history(self, work_type: str | None = None) -> dict[str, Any]:
        """Devolve o histórico de calibração (mudanças e decisões)."""
        changes = self._store.list_changes(work_type=work_type, active=None)
        records: list[CalibrationRecord] = []
        for change in changes:
            records.extend(self._store.list_records(change.id))
        return {
            "schema_version": CALIBRATION_SCHEMA_VERSION,
            "changes": [
                {
                    "id": c.id,
                    "work_type": c.work_type,
                    "parameter": c.parameter,
                    "previous_value": c.previous_value,
                    "new_value": c.new_value,
                    "origin": c.origin,
                    "active": c.active,
                    "created_at": c.created_at,
                }
                for c in changes
            ],
            "records": [
                {
                    "id": r.id,
                    "change_id": r.change_id,
                    "decision": r.decision,
                    "confidence": r.confidence,
                    "improvement": r.improvement,
                    "regression": r.regression,
                    "samples": r.samples,
                    "applied_at": r.applied_at,
                    "reverted_at": r.reverted_at,
                    "reason": r.reason,
                }
                for r in records
            ],
        }


def _dump(value: Any) -> str:
    """Serializa um valor para texto no banco."""
    import json

    return json.dumps(value, ensure_ascii=False, default=str)


def _load(value: str) -> Any:
    """Desserializa um valor armazenado."""
    import json

    try:
        return json.loads(value)
    except Exception:
        return value


def _row_to_change(row: sqlite3.Row) -> CalibrationChange:
    return CalibrationChange(
        id=row["id"],
        work_type=row["work_type"],
        parameter=row["parameter"],
        previous_value=_load(row["previous_value"]),
        new_value=_load(row["new_value"]),
        origin=row["origin"],
        justification=row["justification"],
        hypothesis=row["hypothesis"],
        version=row["version"],
        scenario=row["scenario"],
        created_at=row["created_at"],
        active=bool(row["active"]),
    )


def _row_to_record(row: sqlite3.Row) -> CalibrationRecord:
    return CalibrationRecord(
        id=row["id"],
        change_id=row["change_id"],
        champion_metrics=_load(row["champion_metrics"]),
        challenger_metrics=_load(row["challenger_metrics"]),
        decision=row["decision"],
        confidence=row["confidence"],
        improvement=row["improvement"],
        regression=bool(row["regression"]),
        samples=row["samples"],
        created_at=row["created_at"],
        applied_at=row["applied_at"],
        reverted_at=row["reverted_at"],
        reason=row["reason"],
    )


def _metrics_to_dict(m: CalibrationMetrics) -> dict[str, Any]:
    return {
        "success_rate": m.success_rate,
        "tokens_per_task": m.tokens_per_task,
        "calls_per_task": m.calls_per_task,
        "duration_ms": m.duration_ms,
        "false_completion_rate": m.false_completion_rate,
        "recovery_count": m.recovery_count,
    }


def _relative_improvement(champion: CalibrationMetrics, challenger: CalibrationMetrics) -> float:
    """Melhoria relativa do desafiador sobre o campeão (positivo = melhor)."""
    if champion.success_rate <= 0:
        return 0.0
    # Combina taxa de sucesso, tokens e duração; regressão de sucesso anula.
    if challenger.success_rate < champion.success_rate:
        return -1.0
    token_gain = (
        (champion.tokens_per_task - challenger.tokens_per_task) / champion.tokens_per_task
        if champion.tokens_per_task > 0 else 0.0
    )
    time_gain = (
        (champion.duration_ms - challenger.duration_ms) / champion.duration_ms
        if champion.duration_ms > 0 else 0.0
    )
    return (token_gain + time_gain) / 2.0


def _has_regression(champion: CalibrationMetrics, challenger: CalibrationMetrics) -> bool:
    """Regressão de qualidade: sucesso menor ou falsos completos maiores."""
    return (
        challenger.success_rate < champion.success_rate
        or challenger.false_completion_rate > champion.false_completion_rate
    )


def create_calibration_store(db_path: str) -> CalibrationStore:
    """Factory para criar o armazenamento de calibração.

    Args:
        db_path: caminho do banco SQLite de calibração.

    Returns:
        Instância de CalibrationStore.
    """
    return CalibrationStore(db_path)


def create_calibration_engine(store: CalibrationStore) -> CalibrationEngine:
    """Factory para criar o motor de calibração.

    Args:
        store: armazenamento de calibração.

    Returns:
        Instância de CalibrationEngine.
    """
    return CalibrationEngine(store)
