"""
Arquivo: tests/test_database_url.py
Nome: test_database_url.py
Propósito: verificar de onde o Callidus tira a URL do banco e que um DATABASE_URL de outro banco não derruba a subida.
Responsabilidade: camada de testes — prioridade de CALLIDUS_DATABASE_URL, URL SQLite respeitada e URL não SQLite trocada pelo banco padrão com aviso.
Componentes: Settings.resolved_database_url fora do modo de teste.
Dependências: agent.config, pytest.
Observações: o modo de teste (`PYTEST_CURRENT_TEST`) é desligado dentro de cada teste para exercitar o caminho real; o banco fica em tmp_path.
"""

import logging

from agent.config import Settings


def _fora_do_pytest(monkeypatch):
    """Exercita o caminho de uso real: sem a variável que o pytest define, a URL configurada vale."""
    import agent.config

    monkeypatch.setattr(agent.config, "_WARNED_SCHEMES", set())
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("CALLIDUS_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)


def test_postgres_database_url_from_another_project_falls_back_to_sqlite(monkeypatch, tmp_path, caplog):
    """Regressão: DATABASE_URL=postgres://... exportado no terminal fazia o callidus-api cair com
    NoSuchModuleError na subida; agora o Callidus usa data/agent.db e explica no log."""
    _fora_do_pytest(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgres://usuario@localhost:5432/outro_projeto")
    settings = Settings(data_dir=tmp_path / "data", _env_file=None)

    with caplog.at_level(logging.WARNING, logger="agent.config"):
        url = settings.resolved_database_url()

    assert url == f"sqlite:///{(tmp_path / 'data' / 'agent.db').resolve()}"
    assert "CALLIDUS_DATABASE_URL" in caplog.text and "postgres" in caplog.text


def test_callidus_database_url_wins_over_the_generic_name(monkeypatch, tmp_path):
    """CALLIDUS_DATABASE_URL vence o DATABASE_URL genérico; uma URL SQLite é usada como veio."""
    _fora_do_pytest(monkeypatch)
    proprio = f"sqlite:///{tmp_path / 'meu.db'}"
    monkeypatch.setenv("DATABASE_URL", "postgres://outro")
    monkeypatch.setenv("CALLIDUS_DATABASE_URL", proprio)

    assert Settings(data_dir=tmp_path / "data", _env_file=None).resolved_database_url() == proprio
    assert Settings(database_url=proprio, _env_file=None).resolved_database_url() == proprio
