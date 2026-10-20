"""
Arquivo: src/agent/api/deps.py
Nome: deps.py
Propósito: dependências FastAPI.
Responsabilidade: camada de apresentação/transport.
Componentes: get_engine, get_session_factory, db_session, read_settings.
Dependências: agent.config, agent.persistence.database, __future__, collections.abc, sqlalchemy.orm.
Observações: a rota valida, delega e serializa — a regra de negócio vive no serviço.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session, sessionmaker

from agent.config import Settings, get_settings
from agent.persistence.database import build_session_factory, create_db_engine, init_db

_engine = None
_session_factory: sessionmaker[Session] | None = None


def get_engine():
    """Devolve o motor do banco, criando-o na primeira chamada.

    Returns:
        O motor SQLAlchemy do processo, já inicializado com o esquema do Callidus.
    """
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        _engine = init_db(settings=settings)
        _session_factory = build_session_factory(_engine)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Devolve a fábrica de sessões ligada ao motor do processo.

    Returns:
        A fábrica capaz de abrir sessões de banco para as requisições.
    """
    get_engine()
    assert _session_factory is not None
    return _session_factory


def db_session() -> Generator[Session, None, None]:
    """Fornece a sessão do banco à requisição e fecha o ciclo de transação.

    Yields:
        Uma sessão de banco para a requisição.

    Observações:
        A sessão é confirmada ao final da requisição e revertida quando a rota levanta exceção.
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def read_settings() -> Settings:
    """Fornece as configurações do processo à requisição.

    Returns:
        As configurações carregadas do ambiente e dos arquivos de configuração.
    """
    return get_settings()
