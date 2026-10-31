"""
Arquivo: tests/test_inspection_index.py
Nome: test_inspection_index.py
Propósito: verificar o índice de inspeção de arquivos com hash, versão e relevância.
Responsabilidade: camada de testes — registro de inspeção, detecção de stale por hash,
pontuação de relevância, rank por relevância e persistência nos metadados da tarefa.
Dependências: agent.memory.inspection (FileInspection, InspectionIndex, record_inspection,
is_stale, relevance_score, rank_by_relevance), pytest.
Observações: testes puros, sem banco nem sistema de arquivos real (usam tmp_path).
"""

from agent.memory.inspection import (
    FileInspection,
    InspectionIndex,
    is_stale,
    rank_by_relevance,
    record_inspection,
    relevance_score,
)


def test_file_inspection_roundtrip():
    """FileInspection serializa e reconstrói sem perder campos."""
    insp = FileInspection(
        path="src/main.py",
        hash="abc123",
        size=1234,
        lines=42,
        summary="resumo do arquivo",
        snippets=["def foo():", "class Bar:"],
        collected_at="2026-01-01T00:00:00Z",
        relevance=85,
    )
    data = insp.to_dict()
    restored = FileInspection.from_dict(data)
    assert restored.path == "src/main.py"
    assert restored.hash == "abc123"
    assert restored.size == 1234
    assert restored.lines == 42
    assert restored.summary == "resumo do arquivo"
    assert restored.snippets == ["def foo():", "class Bar:"]
    assert restored.collected_at == "2026-01-01T00:00:00Z"
    assert restored.relevance == 85


def test_index_from_and_to_metadata(tmp_path):
    """InspectionIndex constrói a partir dos metadados e volta para eles."""
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "a.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    index = InspectionIndex()
    record_inspection(
        index,
        "src/a.py",
        str(tmp_path),
        "def hello():\n    return 1\n",
        objective="implementar hello",
    )
    meta_items = index.to_metadata()
    assert len(meta_items) == 1
    assert meta_items[0]["path"] == "src/a.py"
    assert meta_items[0]["hash"]

    index2 = InspectionIndex.from_metadata({"inspection": meta_items})
    assert len(index2) == 1
    assert index2.get("src/a.py") is not None
    assert index2.get("src/a.py").hash == meta_items[0]["hash"]


def test_record_inspection_stores_hash_and_relevance(tmp_path):
    """record_inspection grava hash, tamanho, linhas e relevância."""
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "main.py").write_text("def main():\n    print('oi')\n", encoding="utf-8")
    index = InspectionIndex()
    insp = record_inspection(index, "src/main.py", str(tmp_path), "def main():\n    print('oi')\n", objective="main")
    assert insp.hash
    assert insp.size > 0
    assert insp.lines == 3
    assert 0 <= insp.relevance <= 100
    assert insp.collected_at


def test_is_stale_detects_missing_and_changed(tmp_path):
    """is_stale é True para arquivo sem inspeção e para arquivo alterado."""
    (tmp_path / "src").mkdir(parents=True)
    f = tmp_path / "src" / "a.py"
    f.write_text("v1\n", encoding="utf-8")
    index = InspectionIndex()
    # Sem inspeção: está stale.
    assert is_stale(index, "src/a.py", str(tmp_path)) is True
    # Após inspeção: não está stale.
    record_inspection(index, "src/a.py", str(tmp_path), "v1\n", objective="x")
    assert is_stale(index, "src/a.py", str(tmp_path)) is False
    # Arquivo mudou no disco: fica stale novamente.
    f.write_text("v2\n", encoding="utf-8")
    assert is_stale(index, "src/a.py", str(tmp_path)) is True


def test_relevance_score_bounds():
    """relevance_score fica entre 0 e 100."""
    assert relevance_score("", "qualquer coisa", []) == 0
    assert relevance_score("qualquer coisa", "", []) == 0
    score = relevance_score("implementar login", "def login():\n    return True\n", ["def login():"])
    assert 0 <= score <= 100
    # Conteúdo sem relação com o objetivo pontua baixo.
    low = relevance_score("criar banco de dados", "def hello_world():\n    print('oi')\n", [])
    assert low < 50
    # Conteúdo com muitas palavras em comum pontua alto.
    high = relevance_score(
        "implementar login e autenticação",
        "def login():\n    autenticar_usuario()\n    fazer_login()\n",
        ["def login():", "autenticar_usuario()"],
    )
    assert high > low


def test_rank_by_relevance_orders_descending():
    """rank_by_relevance devolve itens ordenados por relevância decrescente."""
    index = InspectionIndex()
    record_inspection(index, "a.py", "/tmp", "x y z", objective="implementar login")
    record_inspection(index, "b.py", "/tmp", "login autenticar senha", objective="implementar login")
    record_inspection(index, "c.py", "/tmp", "oi mundo tudo bem", objective="implementar login")
    ranked = rank_by_relevance(index, limit=3)
    assert len(ranked) == 3
    assert ranked[0].relevance >= ranked[1].relevance >= ranked[2].relevance
    assert ranked[0].path == "b.py"  # mais relevante


def test_rank_by_relevance_respects_limit():
    """rank_by_relevance respeita o limite."""
    index = InspectionIndex()
    for i in range(5):
        record_inspection(index, f"{i}.py", "/tmp", f"conteudo {i}", objective="x")
    ranked = rank_by_relevance(index, limit=2)
    assert len(ranked) == 2
