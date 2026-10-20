# src/agent/persistence/database.py — engine e sessões SQLAlchemy
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from agent.config import Settings, get_settings
from agent.persistence.models import Base


def _configure_sqlite(engine: Engine) -> None:
    if engine.url.get_backend_name() != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_db_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    engine = create_engine(
        settings.resolved_database_url(),
        connect_args={"check_same_thread": False},
    )
    _configure_sqlite(engine)
    return engine


def _add_column(conn, table: str, column: str, ddl: str) -> None:
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    if not rows:
        return
    cols = {row[1] for row in rows}
    if column not in cols:
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _migrate_sqlite(engine: Engine) -> None:
    if engine.url.get_backend_name() != "sqlite":
        return
    with engine.connect() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(execution_runs)").fetchall()
        cols = {r[1] for r in rows}
        if rows and "config_json" not in cols:
            conn.exec_driver_sql("ALTER TABLE execution_runs ADD COLUMN config_json JSON")
        _add_column(conn, "tasks", "conversation_id", "CHAR(32)")
        _add_column(conn, "memory_records", "conversation_id", "CHAR(32)")
        _add_column(conn, "memory_records", "summary", "TEXT")
        _add_column(conn, "memory_records", "outline_json", "JSON")
        _add_column(conn, "projects", "path_origin", "VARCHAR(16) DEFAULT 'chosen'")
        _add_column(conn, "conversations", "root_path", "VARCHAR(2048)")
        _add_column(conn, "conversations", "active_branch_id", "CHAR(32)")
        _add_column(conn, "tasks", "branch_id", "CHAR(32)")
        _add_column(conn, "memory_records", "branch_id", "CHAR(32)")
        _add_column(conn, "event_logs", "seq", "INTEGER")
        _add_column(conn, "event_logs", "parent_task_id", "CHAR(32)")
        _add_column(conn, "event_logs", "agent", "VARCHAR(64)")
        _add_column(conn, "event_logs", "schema_version", "INTEGER")
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_event_logs_run_seq ON event_logs (run_id, seq)"
        )
        conn.commit()


def migrate_legacy_schedules(engine: Engine) -> int:
    """Converte as linhas antigas de `scheduled_runs` em automações.

    A tabela antiga **não** é apagada: os dados continuam lá para inspeção e a migração
    é idempotente (cada linha antiga vira no máximo uma automação). Uma linha antiga
    só define gatilho e projeto; a ação vira uma automação Callidus sobre o projeto.
    """
    from sqlalchemy import select

    from agent.persistence.models import AutomationModel, ScheduledRunModel

    factory = build_session_factory(engine)
    session = factory()
    try:
        legacy = list(session.scalars(select(ScheduledRunModel)).all())
        created = 0
        for row in legacy:
            existing = session.get(AutomationModel, row.id)
            if existing is not None:
                continue
            legacy_config = dict(row.config_json or {})
            objective = legacy_config.get("objective") or legacy_config.get("prompt")
            automation = AutomationModel(
                id=row.id,
                project_id=row.project_id,
                name=f"Agendamento herdado ({row.cron_expression})",
                description=(
                    "Convertido de `scheduled_runs` na migração das automações. "
                    f"Linha antiga: {row.id}. Revise e ative quando fizer sentido."
                ),
                contract_version=1,
                target_kind="local",
                trigger_json={
                    "kind": "cron",
                    "cron": row.cron_expression,
                    "timezone": "UTC",
                    "missed_policy": "run_once",
                },
                action_json={
                    "kind": "callidus",
                    "objective_mode": "latest",
                    "objective": objective,
                    "autonomous": True,
                },
                dependencies_json=[],
                permissions_json={"allow_scripts": False, "allowed_commands": []},
                policy_json={"max_attempts": 3, "timeout_sec": None, "backoff_sec": 30.0},
                timezone="UTC",
                missed_policy="run_once",
                # Nasce **desabilitada**: o agendamento antigo nunca chegou a rodar
                # (o protótipo criava um run inválido), então a decisão de executá-lo
                # é do usuário, não da migração.
                state="disabled",
                max_attempts=3,
                last_run_at=row.last_run_at,
                next_run_at=None,
            )
            session.add(automation)
            created += 1
        session.commit()
        return created
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(engine: Engine | None = None, settings: Settings | None = None) -> Engine:
    engine = engine or create_db_engine(settings)
    Base.metadata.create_all(engine)
    _migrate_sqlite(engine)
    migrate_legacy_schedules(engine)
    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    from agent.observability.emitter import install

    install()
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
