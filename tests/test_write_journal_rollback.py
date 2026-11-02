"""
Arquivo: tests/test_write_journal_rollback.py
Nome: test_write_journal_rollback.py
Propósito: verificar que o rollback de uma tentativa só desfaz o que ela gravou e preserva alterações de terceiros.
Responsabilidade: camada de testes — comportamento do WriteJournal (remember → settle → restore).
Componentes: rollback normal, conflito com edição externa, arquivo novo preservado, caminho inválido.
Dependências: agent.orchestrator.execution.writes, pytest.
Observações: só filesystem temporário.
"""
from __future__ import annotations

from pathlib import Path

from agent.orchestrator.execution.writes import WriteJournal


def _write(journal: WriteJournal, root: Path, name: str, content: str) -> None:
    """Simula a escrita de uma ferramenta: lembra o original, grava, anota o resultado."""
    journal.remember("write_file", name)
    (root / name).write_text(content, encoding="utf-8")
    journal.settle("write_file", name)


def test_restore_reverts_only_the_attempt_write(tmp_path: Path):
    """A escrita reprovada volta ao original."""
    (tmp_path / "a.py").write_text("ok = 1\n", encoding="utf-8")
    journal = WriteJournal(str(tmp_path))
    _write(journal, tmp_path, "a.py", "ok = (\n")
    assert journal.restore() == [str((tmp_path / "a.py").resolve())]
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "ok = 1\n"
    assert journal.conflicts == []


def test_restore_preserves_changes_made_after_the_attempt(tmp_path: Path):
    """Se outra mão alterou o arquivo depois da escrita da etapa, o rollback não sobrescreve."""
    (tmp_path / "a.py").write_text("ok = 1\n", encoding="utf-8")
    journal = WriteJournal(str(tmp_path))
    _write(journal, tmp_path, "a.py", "ok = 2\n")
    (tmp_path / "a.py").write_text("ok = 2\n# nota da pessoa\n", encoding="utf-8")
    assert journal.restore() == []
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "ok = 2\n# nota da pessoa\n"
    assert journal.conflicts == [str((tmp_path / "a.py").resolve())]


def test_new_files_are_never_deleted(tmp_path: Path):
    """Arquivo criado pela etapa fica (apagar é decisão do dono) e fica marcado como criado."""
    journal = WriteJournal(str(tmp_path))
    _write(journal, tmp_path, "novo.py", "x = 1\n")
    assert journal.restore() == []
    assert (tmp_path / "novo.py").exists()
    assert (tmp_path / "novo.py").resolve() in journal.created


def test_untouched_or_invalid_paths_are_ignored(tmp_path: Path):
    """Nada gravado, caminho vazio ou ferramenta de leitura: o diário não muda nada."""
    journal = WriteJournal(str(tmp_path))
    journal.remember("read_file", "a.py")
    journal.remember("write_file", "")
    journal.settle("write_file", None)
    assert journal.restore() == [] and journal.originals == {} and journal.written == {}


def test_restore_without_settle_keeps_previous_behavior(tmp_path: Path):
    """Sem anotação pós-escrita (caminho antigo), o rollback ainda devolve o original."""
    (tmp_path / "a.py").write_text("ok = 1\n", encoding="utf-8")
    journal = WriteJournal(str(tmp_path))
    journal.remember("edit_file", "a.py")
    (tmp_path / "a.py").write_text("quebrado(\n", encoding="utf-8")
    assert journal.restore()
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == "ok = 1\n"
