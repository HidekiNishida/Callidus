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
        conn.commit()


def init_db(engine: Engine | None = None, settings: Settings | None = None) -> Engine:
    engine = engine or create_db_engine(settings)
    Base.metadata.create_all(engine)
    _migrate_sqlite(engine)
    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
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
