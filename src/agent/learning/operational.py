"""
Arquivo: src/agent/learning/operational.py
Nome: operational.py
Propósito: aprendizado operacional baseado em resultados — histórico de estratégias,
reutilização de experiência, aprendizado seguro.
Responsabilidade: camada de aplicação — registro, recuperação e reutilização de estratégias
bem-sucedidas sem depender de fine-tuning.
Componentes: OperationalLearning, StrategyRecord, ExperienceStore, StrategyRetriever.
Dependências: agent.persistence, agent.domain.enums, json, sqlite3.
Observações: não altera pesos de modelos; aprendizado é operacional, auditável e reversível.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass
class StrategyRecord:
    """Registro de uma estratégia executada."""

    id: str
    task_type: str
    objective_summary: str
    complexity: str
    risk: str
    required_capabilities: list[str]
    strategy: dict[str, Any]
    model_provider: str
    model_id: str
    tools_used: list[str]
    tokens_estimated: int
    tokens_consumed: int
    duration_ms: int
    attempts: int
    verification_result: str
    success: bool
    failure_cause: str | None
    recovery_strategy: str | None
    created_at: str
    project_version: str
    confidence: float


@dataclass
class StrategyQuery:
    """Consulta para recuperar estratégias relevantes."""

    task_type: str | None = None
    objective_keywords: list[str] | None = None
    complexity: str | None = None
    risk: str | None = None
    required_capabilities: list[str] | None = None
    min_confidence: float = 0.5
    limit: int = 5


class ExperienceStore:
    """Armazenamento persistente de experiências operacionais."""

    def __init__(self, db_path: str) -> None:
        """Inicializa o armazenamento.

        Args:
            db_path: caminho do banco SQLite.
        """
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Cria as tabelas se não existirem."""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_records (
                    id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    objective_summary TEXT NOT NULL,
                    complexity TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    required_capabilities TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    model_provider TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    tools_used TEXT NOT NULL,
                    tokens_estimated INTEGER NOT NULL,
                    tokens_consumed INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    attempts INTEGER NOT NULL,
                    verification_result TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    failure_cause TEXT,
                    recovery_strategy TEXT,
                    created_at TEXT NOT NULL,
                    project_version TEXT NOT NULL,
                    confidence REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_strategy_task_type
                ON strategy_records (task_type)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_strategy_success
                ON strategy_records (success)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_strategy_created_at
                ON strategy_records (created_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_strategy_confidence
                ON strategy_records (confidence)
                """
            )

    @contextmanager
    def _connect(self):
        """Conexão com transação."""
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

    def save(self, record: StrategyRecord) -> None:
        """Salva um registro de estratégia.

        Args:
            record: registro a salvar.
        """
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO strategy_records (
                    id, task_type, objective_summary, complexity, risk,
                    required_capabilities, strategy, model_provider, model_id,
                    tools_used, tokens_estimated, tokens_consumed, duration_ms,
                    attempts, verification_result, success, failure_cause,
                    recovery_strategy, created_at, project_version, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.task_type,
                    record.objective_summary,
                    record.complexity,
                    record.risk,
                    json.dumps(record.required_capabilities),
                    json.dumps(record.strategy),
                    record.model_provider,
                    record.model_id,
                    json.dumps(record.tools_used),
                    record.tokens_estimated,
                    record.tokens_consumed,
                    record.duration_ms,
                    record.attempts,
                    record.verification_result,
                    1 if record.success else 0,
                    record.failure_cause,
                    record.recovery_strategy,
                    record.created_at,
                    record.project_version,
                    record.confidence,
                ),
            )

    def query(self, query: StrategyQuery) -> list[StrategyRecord]:
        """Busca estratégias relevantes.

        Args:
            query: critérios de busca.

        Returns:
            Lista de registros ordenados por confiança e recência.
        """
        conditions = ["confidence >= ?"]
        params: list[Any] = [query.min_confidence]

        if query.task_type:
            conditions.append("task_type = ?")
            params.append(query.task_type)

        if query.complexity:
            conditions.append("complexity = ?")
            params.append(query.complexity)

        if query.risk:
            conditions.append("risk = ?")
            params.append(query.risk)

        if query.required_capabilities:
            # Busca por sobreposição de capacidades - verifica cada capacidade individualmente
            for cap in query.required_capabilities:
                conditions.append("required_capabilities LIKE ?")
                params.append(f"%{cap}%")

        if query.objective_keywords:
            # Busca textual simples no resumo do objetivo
            keyword_conditions = []
            for kw in query.objective_keywords:
                keyword_conditions.append("objective_summary LIKE ?")
                params.append(f"%{kw}%")
            if keyword_conditions:
                conditions.append(f"({' OR '.join(keyword_conditions)})")

        where_clause = " AND ".join(conditions)
        sql = f"""
            SELECT * FROM strategy_records
            WHERE {where_clause}
            ORDER BY confidence DESC, created_at DESC
            LIMIT ?
        """
        params.append(query.limit)

        with self._connect() as conn:
            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()

        return [self._row_to_record(row) for row in rows]

    def get_statistics(self) -> dict[str, Any]:
        """Obtém estatísticas do armazenamento."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM strategy_records").fetchone()[0]
            success = conn.execute("SELECT COUNT(*) FROM strategy_records WHERE success = 1").fetchone()[0]
            by_type = conn.execute(
                "SELECT task_type, COUNT(*), SUM(success) FROM strategy_records GROUP BY task_type"
            ).fetchall()

        return {
            "total_records": total,
            "successful_records": success,
            "success_rate": success / total if total > 0 else 0.0,
            "by_task_type": {
                row[0]: {"total": row[1], "success": row[2], "rate": row[2] / row[1] if row[1] > 0 else 0.0}
                for row in by_type
            },
        }

    def _row_to_record(self, row: sqlite3.Row) -> StrategyRecord:
        """Converte linha do banco para StrategyRecord."""
        return StrategyRecord(
            id=row["id"],
            task_type=row["task_type"],
            objective_summary=row["objective_summary"],
            complexity=row["complexity"],
            risk=row["risk"],
            required_capabilities=json.loads(row["required_capabilities"]),
            strategy=json.loads(row["strategy"]),
            model_provider=row["model_provider"],
            model_id=row["model_id"],
            tools_used=json.loads(row["tools_used"]),
            tokens_estimated=row["tokens_estimated"],
            tokens_consumed=row["tokens_consumed"],
            duration_ms=row["duration_ms"],
            attempts=row["attempts"],
            verification_result=row["verification_result"],
            success=bool(row["success"]),
            failure_cause=row["failure_cause"],
            recovery_strategy=row["recovery_strategy"],
            created_at=row["created_at"],
            project_version=row["project_version"],
            confidence=row["confidence"],
        )


class StrategyRetriever:
    """Recupera estratégias relevantes para uma nova tarefa."""

    def __init__(self, store: ExperienceStore) -> None:
        """Inicializa o recuperador.

        Args:
            store: armazenamento de experiências.
        """
        self._store = store

    def find_relevant(
        self,
        task_type: str,
        objective: str,
        complexity: str,
        risk: str,
        required_capabilities: list[str],
    ) -> list[StrategyRecord]:
        """Encontra estratégias relevantes para a tarefa.

        Args:
            task_type: tipo da tarefa.
            objective: objetivo da tarefa.
            complexity: complexidade estimada.
            risk: risco estimado.
            required_capabilities: capacidades requeridas.

        Returns:
            Lista de estratégias relevantes, ordenadas por relevância.
        """
        # Extrai palavras-chave do objetivo
        keywords = self._extract_keywords(objective)

        query = StrategyQuery(
            task_type=task_type,
            objective_keywords=keywords,
            complexity=complexity,
            risk=risk,
            required_capabilities=required_capabilities,
            min_confidence=0.4,
            limit=10,
        )

        return self._store.query(query)

    def _extract_keywords(self, text: str) -> list[str]:
        """Extrai palavras-chave relevantes do texto."""
        # Remove pontuação e converte para minúsculas
        import re

        words = re.findall(r"\b\w+\b", text.lower())
        # Filtra stopwords simples
        stopwords = {
            "a",
            "o",
            "e",
            "de",
            "da",
            "do",
            "em",
            "para",
            "com",
            "um",
            "uma",
            "os",
            "as",
            "dos",
            "das",
            "no",
            "na",
            "nos",
            "nas",
            "por",
            "pelo",
            "pela",
            "se",
            "que",
            "como",
            "quando",
            "onde",
            "porque",
            "mais",
            "menos",
            "muito",
            "pouco",
            "bem",
            "mal",
            "sim",
            "não",
            "the",
            "to",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "for",
            "with",
            "from",
            "by",
        }
        keywords = [w for w in words if len(w) > 3 and w not in stopwords]
        # Retorna as 10 palavras mais frequentes
        from collections import Counter

        return [w for w, _ in Counter(keywords).most_common(10)]


class OperationalLearning:
    """Sistema de aprendizado operacional.

    Registra estratégias executadas, recupera experiências relevantes
    e permite reutilização segura sem fine-tuning.
    """

    def __init__(self, db_path: str) -> None:
        """Inicializa o aprendizado operacional.

        Args:
            db_path: caminho do banco de dados.
        """
        self._store = ExperienceStore(db_path)
        self._retriever = StrategyRetriever(self._store)

    def record_execution(
        self,
        *,
        task_type: str,
        objective: str,
        complexity: str,
        risk: str,
        required_capabilities: list[str],
        strategy: dict[str, Any],
        model_provider: str,
        model_id: str,
        tools_used: list[str],
        tokens_estimated: int,
        tokens_consumed: int,
        duration_ms: int,
        attempts: int,
        verification_result: str,
        success: bool,
        failure_cause: str | None = None,
        recovery_strategy: str | None = None,
        project_version: str = "unknown",
    ) -> StrategyRecord:
        """Registra a execução de uma estratégia.

        Args:
            task_type: tipo da tarefa (bug, feature, refactor, etc.).
            objective: objetivo da tarefa.
            complexity: complexidade (simple, moderate, complex, critical).
            risk: risco (low, medium, high, critical).
            required_capabilities: capacidades requeridas.
            strategy: estratégia executada (plano, decomposição, etc.).
            model_provider: provedor do modelo.
            model_id: ID do modelo.
            tools_used: ferramentas utilizadas.
            tokens_estimated: tokens estimados.
            tokens_consumed: tokens efetivamente consumidos.
            duration_ms: duração em milissegundos.
            attempts: número de tentativas.
            verification_result: resultado da verificação.
            success: se foi bem-sucedido.
            failure_cause: causa da falha (se houver).
            recovery_strategy: estratégia de recuperação usada (se houver).
            project_version: versão do projeto.

        Returns:
            O registro criado.
        """
        # Calcula confiança baseada no resultado
        confidence = self._calculate_confidence(
            success=success,
            attempts=attempts,
            verification_result=verification_result,
        )

        record = StrategyRecord(
            id=str(uuid.uuid4()),
            task_type=task_type,
            objective_summary=objective[:200],
            complexity=complexity,
            risk=risk,
            required_capabilities=required_capabilities,
            strategy=strategy,
            model_provider=model_provider,
            model_id=model_id,
            tools_used=tools_used,
            tokens_estimated=tokens_estimated,
            tokens_consumed=tokens_consumed,
            duration_ms=duration_ms,
            attempts=attempts,
            verification_result=verification_result,
            success=success,
            failure_cause=failure_cause,
            recovery_strategy=recovery_strategy,
            created_at=datetime.now(UTC).isoformat(),
            project_version=project_version,
            confidence=confidence,
        )

        self._store.save(record)
        return record

    def _calculate_confidence(
        self,
        success: bool,
        attempts: int,
        verification_result: str,
    ) -> float:
        """Calcula a confiança do registro."""
        base = 1.0 if success else 0.0
        # Penaliza múltiplas tentativas
        attempt_penalty = min(0.3, (attempts - 1) * 0.1)
        # Ajusta por resultado de verificação
        verification_bonus = {
            "validated": 0.2,
            "requirement_satisfied": 0.3,
            "completed": 0.4,
            "executed": 0.0,
            "failed": -0.2,
        }.get(verification_result, 0.0)

        confidence = base - attempt_penalty + verification_bonus
        return max(0.0, min(1.0, confidence))

    def get_recommendations(
        self,
        task_type: str,
        objective: str,
        complexity: str,
        risk: str,
        required_capabilities: list[str],
    ) -> list[dict[str, Any]]:
        """Obtém recomendações baseadas em experiências passadas.

        Args:
            task_type: tipo da tarefa.
            objective: objetivo da tarefa.
            complexity: complexidade.
            risk: risco.
            required_capabilities: capacidades requeridas.

        Returns:
            Lista de recomendações com estratégias, modelos e ferramentas sugeridos.
        """
        records = self._retriever.find_relevant(
            task_type=task_type,
            objective=objective,
            complexity=complexity,
            risk=risk,
            required_capabilities=required_capabilities,
        )

        if not records:
            return []

        # Agrupa por estratégia similar e calcula métricas
        recommendations = []
        for record in records:
            if record.confidence < 0.4:
                continue

            recommendations.append(
                {
                    "strategy": record.strategy,
                    "model_provider": record.model_provider,
                    "model_id": record.model_id,
                    "tools_used": record.tools_used,
                    "estimated_tokens": record.tokens_consumed,
                    "estimated_duration_ms": record.duration_ms,
                    "success_rate": 1.0 if record.success else 0.0,
                    "confidence": record.confidence,
                    "similarity_factors": self._similarity_factors(record, objective),
                }
            )

        return recommendations

    def _similarity_factors(self, record: StrategyRecord, objective: str) -> list[str]:
        """Identifica fatores de similaridade."""
        factors = []
        if record.task_type in objective.lower():
            factors.append("tipo de tarefa")
        if any(cap in record.required_capabilities for cap in ["tools", "tool_loop"]):
            factors.append("uso de ferramentas")
        if record.complexity in objective.lower():
            factors.append("complexidade")
        return factors

    def get_statistics(self) -> dict[str, Any]:
        """Obtém estatísticas do aprendizado."""
        return self._store.get_statistics()


def create_operational_learning(db_path: str) -> OperationalLearning:
    """Factory para criar o aprendizado operacional.

    Args:
        db_path: caminho do banco de dados.

    Returns:
        Instância do OperationalLearning.
    """
    return OperationalLearning(db_path)
