"""
Arquivo: tests/test_execution_package.py
Nome: test_execution_package.py
Propósito: verificar o pacote de execução de tarefa (permissões de escrita, payload do modelo, escolha de provedor e despacho da etapa).
Responsabilidade: camada de testes — comportamento das regras puras e do executor de uma etapa.
Componentes: guards (recusa de escrita, ferramentas liberadas, payload), writes (payload→ferramenta, critério implícito), tool_results (resultado de teste), providers (escolha do provedor), runtime e TaskExecutor.
Dependências: agent.orchestrator.execution, agent.services (project, task, run), agent.persistence.database, pytest.
Observações: banco SQLite temporário e filesystem temporário por teste; nenhum provedor real é chamado.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from agent.config import Settings
from agent.domain.enums import TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.execution import (
    ExecutionRuntime,
    TaskExecutor,
    is_informative_test_result,
    operation_tools_for,
    payload_is_usable,
    select_provider,
    test_summary as summarize_tests,
    work_root,
    write_refusal_reason,
)
from agent.orchestrator.execution.guards import evidence_state
from agent.orchestrator.execution.writes import (
    implicit_spec,
    model_refusal_result,
    write_tool_from_payload,
)
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EvidenceModel
from agent.providers.base import ProviderConfigError
from agent.providers.mock import MockProvider
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService


def _promove(session, task) -> None:
    """Move a etapa para `RUNNING` pelas transições válidas da máquina de estados.

    Args:
        session: sessão do banco.
        task: etapa a promover.
    """
    from agent.domain.schemas import TaskStatusUpdate

    service = TaskService(session)
    for status in (TaskStatus.PLANNING, TaskStatus.READY, TaskStatus.RUNNING):
        service.update_status(task.id, TaskStatusUpdate(status=status))


@pytest.fixture
def session(tmp_path: Path):
    """Sessão de banco sobre um diretório de dados temporário, fechada ao fim do teste."""
    engine = init_db(settings=Settings(data_dir=tmp_path / "data"))
    opened = build_session_factory(engine)()
    yield opened
    opened.close()


def test_escrita_e_recusada_em_pedido_somente_leitura():
    """Em pedido somente leitura, a escrita é recusada e a leitura permanece livre."""
    meta = {"read_only": True}
    assert write_refusal_reason(meta, "write_file", "app.py") is not None
    assert write_refusal_reason(meta, "read_file", "app.py") is None


def test_escrita_em_teste_e_recusada_quando_a_regua_esta_protegida():
    """Com a régua protegida, o teste é o critério da medição e não pode ser alterado."""
    meta = {"protect_tests": True}
    assert write_refusal_reason(meta, "write_file", "tests/test_app.py") is not None
    assert write_refusal_reason(meta, "write_file", "app.py") is None


def test_ferramentas_de_escrita_somem_somente_leitura():
    """A etapa somente leitura recebe as ferramentas de leitura, sem as de escrita."""
    somente_leitura = operation_tools_for({"read_only": True})
    assert "write_file" not in somente_leitura
    assert "read_file" in somente_leitura
    assert "write_file" in operation_tools_for({})


def test_payload_do_modelo_somente_e_aceito_com_caminho_e_conteudo():
    """O JSON do modelo só é aceito quando traz caminho e conteúdo."""
    assert payload_is_usable('{"path": "app.py", "content": "x = 1"}') is True
    assert payload_is_usable('{"path": "app.py"}') is False
    assert payload_is_usable("não é json") is False


def test_payload_vira_ferramenta_de_edicao_ou_de_escrita():
    """Trecho a substituir vira edição; conteúdo inteiro vira escrita."""
    tool, args = write_tool_from_payload({"path": "app.py", "old_string": "a", "new_string": "b"})
    assert tool == "edit_file"
    assert args == {"path": "app.py", "old_string": "a", "new_string": "b"}
    tool, args = write_tool_from_payload({"path": "app.py", "content": "b"})
    assert tool == "write_file"
    assert args == {"path": "app.py", "content": "b"}


def test_criterio_implicito_aponta_para_o_que_foi_gravado():
    """A escrita gera um critério implícito de verificação com o conteúdo gravado."""
    spec = implicit_spec("app.py", "x = 1")
    assert spec is not None
    assert spec["type"] == "file_contains"
    assert spec["path"] == "app.py"
    assert spec["contains"] == "x = 1"
    assert implicit_spec("app.py", "   ") is None
    assert implicit_spec(None, "x = 1") is None


def test_suite_que_reprova_e_resultado_e_nao_falha_de_ferramenta():
    """Rodar a suíte e ver os testes falharem é resultado; a ferramenta quebrada é outra coisa."""
    reprovada = {"success": False, "exit_code": 1, "stdout": "1 failed"}
    assert is_informative_test_result("run_pytest", reprovada) is True
    quebrada = {"success": False, "exit_code": None, "stdout": ""}
    assert is_informative_test_result("run_pytest", quebrada) is False
    assert is_informative_test_result("run_command", reprovada) is False
    assert summarize_tests(reprovada) == "1 failed"


def test_recusa_de_escrita_vira_resultado_da_etapa():
    """A recusa é registrada com o motivo, o caminho e o relatório do modelo."""
    result = model_refusal_result("write_file", "app.py", "motivo", report="texto", snapshot_id="s1")
    assert result["refused_write"]["tool"] == "write_file"
    assert result["refused_write"]["reason"] == "motivo"
    assert result["report"] == "texto"
    assert result["context_snapshot_id"] == "s1"


def test_estado_da_evidencia_traduz_o_veredito():
    """O estado gravado na evidência distingue aprovado, reprovado, inconclusivo e bloqueado."""
    assert evidence_state(True) == "aprovado"
    assert evidence_state(False) == "reprovado"
    assert evidence_state(None) == "inconclusivo"
    assert evidence_state(None, blocked=True) == "bloqueado"


def test_provedor_desconhecido_e_erro_e_nao_fallback_para_o_mock():
    """Nome de provedor desconhecido falha explicitamente — o mock só entra autorizado."""
    settings = Settings(data_dir=Path("/tmp/callidus-test"), allow_mock_fallback=False)
    with pytest.raises(ProviderConfigError):
        select_provider(settings, {"provider": "provedor-que-nao-existe"})
    assert isinstance(select_provider(settings, {"provider": "mock"}), MockProvider)


def test_runtime_monta_os_colaboradores_da_execucao(session, tmp_path: Path):
    """O runtime entrega sessão, configuração, serviço de tarefas, tentativas e ferramentas."""
    runtime = ExecutionRuntime.build(session, Settings(data_dir=tmp_path / "data"))
    assert runtime.session is session
    assert runtime.tasks is not None
    assert runtime.attempts is not None
    assert runtime.tools is not None
    assert runtime.provider_factory is None


@pytest.mark.asyncio
async def test_executor_escreve_o_arquivo_e_verifica_a_etapa(session, tmp_path: Path):
    """A etapa com ferramenta determinística escreve o arquivo e segue para a verificação."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    task = TaskService(session).create_task(
        project.id,
        TaskCreate(
            title="Escrever",
            objective="Escrever o arquivo de exemplo",
            kind="operation",
            metadata={
                "tool": "write_file",
                "tool_args": {"path": "exemplo.txt", "content": "conteúdo"},
            },
        ),
    )
    run = RunService(session).start_run(project.id, ExecutionRunCreate(root_task_id=task.id))
    _promove(session, task)
    runtime = ExecutionRuntime.build(session, Settings(data_dir=tmp_path / "data"))
    executor = TaskExecutor(runtime)

    result = await executor.execute(run, project, task, {}, str(tmp_path))

    assert result["action"] in {"verified_ok", "completed_without_verification"}
    assert (tmp_path / "exemplo.txt").read_text(encoding="utf-8") == "conteúdo"
    assert TaskStatus(task.status) in {TaskStatus.COMPLETED, TaskStatus.VERIFYING}


@pytest.mark.asyncio
async def test_executor_grava_evidencia_quando_a_verificacao_reprova(session, tmp_path: Path):
    """A verificação reprovada grava evidência e devolve a etapa para nova tentativa."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    task = TaskService(session).create_task(
        project.id,
        TaskCreate(
            title="Verificar",
            objective="Verificar um conteúdo que não existe",
            kind="operation",
            metadata={
                "verification": {"type": "file_contains", "path": "ausente.txt", "contains": "x"}
            },
        ),
    )
    run = RunService(session).start_run(project.id, ExecutionRunCreate(root_task_id=task.id))
    _promove(session, task)
    runtime = ExecutionRuntime.build(session, Settings(data_dir=tmp_path / "data"))
    executor = TaskExecutor(runtime)

    result = await executor.execute(run, project, task, {}, str(tmp_path))

    assert result["action"] in {"verify_failed", "verify_blocked", "verify_inconclusive"}
    evidences = session.execute(select(EvidenceModel)).scalars().all()
    assert evidences, "a verificação reprovada precisa deixar evidência"
    assert evidences[0].passed is False


def test_raiz_de_trabalho_usa_a_conversa_da_etapa(session, tmp_path: Path):
    """A raiz de trabalho da etapa é a da conversa quando ela existe."""
    project = ProjectService(session).create_project(ProjectCreate(name="p", root_path=str(tmp_path)))
    task = TaskService(session).create_task(
        project.id, TaskCreate(title="T", objective="o", kind="operation")
    )
    assert work_root(session, project, task) == str(tmp_path)
