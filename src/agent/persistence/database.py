"""
Arquivo: src/agent/persistence/database.py
Nome: database.py
Propósito: criar a engine SQLAlchemy, manter o esquema e abrir sessões de banco.
Responsabilidade: camada de infraestrutura — engine, migrações leves e fábrica de sessões.
Componentes: create_db_engine, init_db, build_session_factory, session_scope, migrate_legacy_schedules.
Dependências: sqlalchemy, agent.config, agent.persistence.models.
Observações: a migração do SQLite é aditiva e idempotente; nenhuma tabela é destruída.
"""
from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from agent.config import Settings, get_settings
from agent.persistence.models import Base


def _configure_sqlite(engine: Engine) -> None:
    """Liga as chaves estrangeiras do SQLite por conexão.

    Args:
        engine: engine alvo; a configuração só se aplica ao backend SQLite.

    Observações:
        O SQLite ignora chaves estrangeiras por padrão; sem este pragma, o banco aceitaria órfãos.
    """
    if engine.url.get_backend_name() != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record) -> None:
        """Aplica um pragma do SQLite na conexão (WAL, chaves estrangeiras, timeout)."""
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def create_db_engine(settings: Settings | None = None) -> Engine:
    """Cria a engine SQLAlchemy apontada para o banco configurado.

    Args:
        settings: configurações a usar; quando ausentes, são lidas do ambiente.

    Returns:
        A engine pronta, já com as chaves estrangeiras habilitadas no SQLite.
    """
    settings = settings or get_settings()
    engine = create_engine(
        settings.resolved_database_url(),
        connect_args={"check_same_thread": False},
    )
    _configure_sqlite(engine)
    return engine


def _add_column(conn, table: str, column: str, ddl: str) -> None:
    """Adiciona uma coluna a uma tabela existente, se ainda não existir.

    Args:
        conn: conexão SQLAlchemy em execução.
        table: nome da tabela alvo.
        column: nome da coluna desejada.
        ddl: definição SQL do tipo e das opções da coluna.

    Observações:
        A tabela e a coluna são consultadas antes; a operação é idempotente.
    """
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    if not rows:
        return
    cols = {row[1] for row in rows}
    if column not in cols:
        conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _migrate_sqlite(engine: Engine) -> None:
    """Aplica as migrações aditivas do esquema SQLite.

    Args:
        engine: engine alvo; nada acontece fora do backend SQLite.

    Observações:
        Cada coluna só é criada quando ausente; a migração é idempotente e nunca apaga dados.
    """
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
    """Cria o esquema e aplica as migrações, deixando o banco pronto para uso.

    Args:
        engine: engine existente; quando ausente, é criada a partir das configurações.
        settings: configurações usadas apenas quando a engine não é informada.

    Returns:
        A engine inicializada.
    """
    engine = engine or create_db_engine(settings)
    Base.metadata.create_all(engine)
    _migrate_sqlite(engine)
    migrate_legacy_schedules(engine)
    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Fábrica de sessões ligada à engine, com o emissor de eventos instalado.

    Args:
        engine: engine que as sessões devem usar.

    Returns:
        Um `sessionmaker` sem autoflush, com commit explícito e sem expirar após commit.
    """
    from agent.observability.emitter import install

    install()
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """Abre uma sessão e garante commit ou rollback no encerramento.

    Args:
        session_factory: fábrica que produce a sessão.

    Yields:
        A sessão aberta; o commit ocorre ao sair sem exceção.

    Raises:
        Exception: qualquer exceção do bloco é propagada após o rollback.

    Observações:
        A sessão é sempre fechada, mesmo em caso de erro.
    """
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
