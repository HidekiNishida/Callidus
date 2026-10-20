"""
Arquivo: tests/test_verification_integrity.py
Nome: test_verification_integrity.py
Propósito: verificar que a evidência precisa provar alguma coisa.
Responsabilidade: camada de testes — comportamento do verificador de etapas e da impressão digital das evidências.
Componentes: etapas sem dependência declarada, reprovação por etapa anterior pendente, aprovação por etapa concluída, evidência invalidada quando o arquivo some ou muda, impressão digital por verificador e verificador de etapas que não se autoaprova.
Dependências: agent.orchestrator.consolidation.stages_outcome, agent.verification (fingerprint, runner), agent.services (project, task), agent.persistence.database, pytest.
Observações: banco e workspace temporários por teste; as evidências são criadas direto no banco.

a evidência precisa provar alguma coisa


Regressões da integridade da verificação.

Duas falhas de fundo permitiam que o Callidus dissesse "concluído" sem ter provado nada:

1. O verificador `stages` devolvia aprovação sem olhar para nada. Agora ele confere as etapas
   das quais a tarefa depende; sem dependência declarada o resultado é inconclusivo.
2. Verificadores que leem um arquivo (`file_exists`, `syntax`) não deixavam impressão digital:
   a evidência continuava válida depois de o arquivo sumir ou mudar.
"""
from pathlib import Path

import pytest

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ProjectCreate, TaskCreate, TaskDependencyCreate
from agent.orchestrator.consolidation import stages_outcome
from agent.persistence.database import build_session_factory, init_db
from agent.services.project_service import ProjectService
from agent.services.task_service import TaskService
from agent.verification.fingerprint import artifact_paths, is_current, snapshot


@pytest.fixture
def session(tmp_path: Path):
    """Sessão de banco sobre um diretório de dados temporário, fechada ao fim do teste."""
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


def _tree(session, tmp_path):
    """Monta uma tarefa raiz com duas etapas, uma delas dependente da outra."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    tasks = TaskService(session)
    root = tasks.create_task(project.id, TaskCreate(title="Raiz", objective="fazer"))
    root.status = TaskStatus.PLANNING.value
    first = tasks.create_task(
        project.id, TaskCreate(title="Primeira", objective="a", parent_id=root.id)
    )
    second = tasks.create_task(
        project.id, TaskCreate(title="Segunda", objective="b", parent_id=root.id)
    )
    session.flush()
    tasks.add_dependency(second.id, TaskDependencyCreate(depends_on_task_id=first.id))
    session.flush()
    return project, root, first, second


def test_stages_sem_dependencia_e_inconclusivo(session, tmp_path):
    """Sem dependência não há o que confirmar: inconclusivo, nunca aprovação automática."""
    project, _, _, _ = _tree(session, tmp_path)
    solta = TaskService(session).create_task(
        project.id, TaskCreate(title="Sem dependência", objective="c")
    )
    session.flush()

    passed, summary, detail = stages_outcome(session, solta)

    assert passed is None
    assert "não declara dependência" in summary
    assert detail["dependencies"] == []


def test_stages_reprova_etapa_anterior_pendente(session, tmp_path):
    """Uma etapa anterior ainda pendente reprova a verificação por etapas."""
    _, _, first, second = _tree(session, tmp_path)
    first.status = TaskStatus.PLANNING.value
    session.flush()

    passed, summary, detail = stages_outcome(session, second)

    assert passed is False
    assert "Primeira" in summary
    assert detail["dependencies"][0]["ok"] is False


def test_stages_aprova_etapa_anterior_concluida(session, tmp_path):
    """Uma etapa anterior concluída aprova a verificação por etapas."""
    _, _, first, second = _tree(session, tmp_path)
    first.status = TaskStatus.COMPLETED.value
    session.flush()

    passed, summary, detail = stages_outcome(session, second)

    assert passed is True
    assert detail["dependencies"][0]["ok"] is True


def test_evidence_de_file_exists_invalida_quando_o_arquivo_some(tmp_path):
    """A evidência de existência de arquivo é invalidada quando o arquivo some."""
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    spec = {"type": "file_exists", "path": "app.py"}

    art = snapshot(str(tmp_path), spec)
    assert art is not None
    assert is_current(art) is True

    (tmp_path / "app.py").unlink()
    assert is_current(art) is False


def test_evidence_de_syntax_invalida_quando_o_arquivo_muda(tmp_path):
    """A evidência de sintaxe é invalidada quando o arquivo muda."""
    target = tmp_path / "app.py"
    target.write_text("x = 1\n", encoding="utf-8")
    spec = {"type": "syntax", "path": "app.py"}

    art = snapshot(str(tmp_path), spec)
    assert art is not None
    assert is_current(art) is True

    target.write_text("x = (\n", encoding="utf-8")
    assert is_current(art) is False


def test_verificadores_que_leem_arquivo_agora_tem_impressao_digital():
    """Os verificadores que leem arquivo passam a ter impressão digital, e os demais continuam sem ela."""
    assert artifact_paths({"type": "file_exists", "path": "a.py"}) == ["a.py"]
    assert artifact_paths({"type": "syntax", "path": "a.py"}) == ["a.py"]
    # Verificadores que não dependem de arquivo continuam sem impressão.
    assert artifact_paths({"type": "stages"}) == []


@pytest.mark.asyncio
async def test_verificador_stages_nao_aprova_sozinho(tmp_path):
    """Chamado direto (sem o orquestrador), `stages` não pode se autoaprovar."""
    from agent.verification.runner import run_verification

    result = await run_verification(
        project_root=str(tmp_path), spec={"type": "stages"}, approved=True
    )

    assert result.passed is None
