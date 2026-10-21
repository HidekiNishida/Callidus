"""
Arquivo: tests/test_automation_chat_tools.py
Nome: test_automation_chat_tools.py
Propósito: Verificar as ferramentas de automação oferecidas ao chat e o serviço que elas chamam.
Responsabilidade: camada de testes — registro, schemas, criação, consulta, alteração, estados, execução e diagnóstico.
Componentes: registro de ferramentas, ciclo completo de uma automação pelo chat, proteções de confirmação e permissão.
Dependências: agent.tools.automations, agent.automation.chat_service, agent.tools.registry.
Observações: banco temporário por teste; nenhuma chamada HTTP — o modelo fala com os serviços.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent.automation.chat_service import AutomationChatError, AutomationChatService
from agent.automation.dispatcher import Dispatcher
from agent.config import Settings
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import AutomationModel, ProjectModel
from agent.tools.automations import register_all
from agent.tools.registry import ToolContext, ToolRegistry, build_default_registry

AUTOMATION_TOOLS = (
    "automation_create",
    "automation_list",
    "automation_get",
    "automation_update",
    "automation_enable",
    "automation_suspend",
    "automation_disable",
    "automation_run_now",
    "automation_test",
    "automation_history",
    "automation_cancel",
    "automation_delete",
    "automation_supervisor_status",
)


@pytest.fixture
def env(tmp_path):
    """Ambiente de teste: banco temporário, projeto e contexto de ferramentas."""
    settings = Settings(data_dir=tmp_path / "data")
    engine = init_db(settings=settings)
    session = build_session_factory(engine)()
    project = ProjectModel(name="projeto", root_path=str(tmp_path))
    session.add(project)
    session.commit()
    ctx = ToolContext(
        project_root=str(tmp_path),
        session=session,
        project_id=str(project.id),
        settings=settings,
    )
    yield {"session": session, "project": project, "ctx": ctx, "settings": settings}
    session.close()


async def _call(ctx: ToolContext, tool: str, **args):
    """Executa uma ferramenta pelo próprio registro (o caminho real do chat)."""
    registry = build_default_registry()
    return await registry.execute(tool, ctx, args, approved=True)


# --------------------------------------------------------------- registro


def test_ferramentas_estao_no_registro_do_chat():
    """As ferramentas de automação estão registradas no registro usado pelo chat."""
    registry = build_default_registry()
    ids = {spec.id for spec in registry.list_specs()}
    for tool in AUTOMATION_TOOLS:
        assert tool in ids
        assert registry.get_spec(tool).description


def test_schema_das_ferramentas_e_estruturado():
    """O schema da criação declara os argumentos tipados que o modelo preenche."""
    registry = build_default_registry()
    schema = registry.get_spec("automation_create").input_schema
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert {"name", "objective", "schedule"} <= set(properties)
    assert properties["action_kind"]["enum"] == ["callidus", "script"]
    assert properties["allow_scripts"]["type"] == "boolean"


def test_registro_personalizado_aceita_as_ferramentas():
    """A registro das ferramentas também funciona em um registro próprio."""
    registry = ToolRegistry()
    register_all(registry)
    assert {spec.id for spec in registry.list_specs()} == set(AUTOMATION_TOOLS)


# ---------------------------------------------------------------- criação


@pytest.mark.asyncio
async def test_criar_automacao_por_linguagem_natural(env):
    """O pedido em português vira uma automação desabilitada, com fuso e próximo disparo."""
    result = await _call(
        env["ctx"],
        "automation_create",
        name="Verificação diária",
        objective="Verificar os testes dos projetos e avisar as falhas",
        schedule="todos os dias às 9h",
    )
    assert result["success"] is True
    automation = result["automation"]
    assert automation["state"] == "disabled"
    assert automation["schedule"]["cron"] == "0 9 * * *"
    assert automation["timezone"] == "America/Sao_Paulo"
    assert automation["next_run_at"] is None
    assert automation["planned_next_run_at_local"]
    assert result["needs_confirmation"] is True
    assert automation["confirmation_token"]

    rows = env["session"].query(AutomationModel).all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_criar_nao_ativa_sem_confirmacao(env):
    """Ativar sem o token da prévia é recusado — a criação não ativa nada."""
    created = await _call(
        env["ctx"],
        "automation_create",
        name="Relatório",
        objective="Preparar o relatório",
        schedule="toda segunda-feira às 8h30",
    )
    automation_id = created["automation"]["id"]
    refused = await _call(env["ctx"], "automation_enable", automation_id=automation_id)
    assert refused["success"] is False
    assert "confirmation_token" in refused["error"]

    row = env["session"].query(AutomationModel).one()
    assert row.state == "disabled"


@pytest.mark.asyncio
async def test_ativar_com_token_da_previa(env):
    """Com o token da prévia, a automação é ativada e o próximo disparo é gravado."""
    created = await _call(
        env["ctx"],
        "automation_create",
        name="Verificação diária",
        objective="Verificar os testes",
        schedule="todos os dias às 9h",
    )
    automation = created["automation"]
    enabled = await _call(
        env["ctx"],
        "automation_enable",
        automation_id=automation["id"],
        confirmation_token=automation["confirmation_token"],
    )
    assert enabled["success"] is True
    assert enabled["automation"]["state"] == "enabled"
    assert enabled["automation"]["next_run_at"] is not None


@pytest.mark.asyncio
async def test_token_invalido_depois_de_mudanca_material(env):
    """Mudou a definição, a confirmação antiga não vale mais."""
    created = await _call(
        env["ctx"],
        "automation_create",
        name="Verificação diária",
        objective="Verificar os testes",
        schedule="todos os dias às 9h",
    )
    automation = created["automation"]
    stale = automation["confirmation_token"]
    updated = await _call(
        env["ctx"],
        "automation_update",
        automation_id=automation["id"],
        schedule="todos os dias às 10h",
    )
    assert updated["success"] is True
    assert updated["automation"]["confirmation_token"] != stale
    assert updated["suspended_pending_confirmation"] is False

    refused = await _call(
        env["ctx"],
        "automation_enable",
        automation_id=automation["id"],
        confirmation_token=stale,
    )
    assert refused["success"] is False
    assert refused["requires_confirmation"] is True


@pytest.mark.asyncio
async def test_criacao_repetida_nao_duplica(env):
    """Repetir a mesma criação devolve a automação existente, sem criar outra."""
    args = {
        "name": "Verificação diária",
        "objective": "Verificar os testes",
        "schedule": "todos os dias às 9h",
    }
    first = await _call(env["ctx"], "automation_create", **args)
    second = await _call(env["ctx"], "automation_create", **args)
    assert second["success"] is True
    assert second["automation"]["id"] == first["automation"]["id"]
    assert env["session"].query(AutomationModel).count() == 1


@pytest.mark.asyncio
async def test_horario_ambiguo_nao_persiste(env):
    """Um horário que não pode ser interpretado não grava automação nenhuma."""
    result = await _call(
        env["ctx"],
        "automation_create",
        name="Vaga",
        objective="Verificar os testes",
        schedule="de manhã",
    )
    assert result["success"] is False
    assert result["question"]
    assert env["session"].query(AutomationModel).count() == 0


@pytest.mark.asyncio
async def test_acao_script_exige_permissao_explicita(env):
    """Criar uma automação de script sem autorização é recusado."""
    result = await _call(
        env["ctx"],
        "automation_create",
        name="Script",
        objective="Rodar o script de verificação",
        schedule="todos os dias às 9h",
        action_kind="script",
        command=["/bin/sh", "-c", "echo ok"],
    )
    assert result["success"] is False
    assert result["requires_permission"] is True
    assert env["session"].query(AutomationModel).count() == 0


@pytest.mark.asyncio
async def test_acao_script_autorizada_registra_permissao(env):
    """Com a autorização explícita, a ação de script é criada com a allowlist."""
    result = await _call(
        env["ctx"],
        "automation_create",
        name="Script",
        objective="Rodar o script de verificação",
        schedule="todos os dias às 9h",
        action_kind="script",
        command=["/bin/sh", "-c", "echo ok"],
        allow_scripts=True,
        allowed_commands=["/bin/sh"],
    )
    assert result["success"] is True
    permissions = result["automation"]["permissions"]
    assert permissions["allow_scripts"] is True
    assert "/bin/sh" in permissions["allowed_commands"]


@pytest.mark.asyncio
async def test_executavel_fora_da_allowlist_e_recusado(env):
    """O executável precisa estar na lista autorizada."""
    result = await _call(
        env["ctx"],
        "automation_create",
        name="Script",
        objective="Rodar o script",
        schedule="todos os dias às 9h",
        action_kind="script",
        command=["/usr/local/bin/qualquer"],
        allow_scripts=True,
        allowed_commands=["/bin/sh"],
    )
    assert result["success"] is False
    assert result["field"] == "allowed_commands"


# -------------------------------------------------------------- consultas


@pytest.mark.asyncio
async def test_listar_consultar_e_remover(env):
    """A automação criada é listada, consultada e removida."""
    created = await _call(
        env["ctx"],
        "automation_create",
        name="Verificação diária",
        objective="Verificar os testes",
        schedule="todos os dias às 9h",
    )
    automation_id = created["automation"]["id"]

    listed = await _call(env["ctx"], "automation_list")
    assert listed["count"] == 1
    assert listed["automations"][0]["id"] == automation_id

    detail = await _call(env["ctx"], "automation_get", automation_id=automation_id)
    assert detail["automation"]["name"] == "Verificação diária"
    assert detail["automation"]["schedule"]["cron"] == "0 9 * * *"

    refused = await _call(env["ctx"], "automation_delete", automation_id=automation_id)
    assert refused["success"] is False

    removed = await _call(
        env["ctx"], "automation_delete", automation_id=automation_id, confirm=True
    )
    assert removed["success"] is True
    assert env["session"].query(AutomationModel).count() == 0


@pytest.mark.asyncio
async def test_consulta_por_nome_com_ambiguidade(env):
    """Dois nomes parecidos produzem candidatos, e nenhuma alteração por deduplicação ingenua."""
    await _call(
        env["ctx"],
        "automation_create",
        name="Relatório semanal",
        objective="Resumo",
        schedule="toda segunda-feira às 8h",
    )
    await _call(
        env["ctx"],
        "automation_create",
        name="Relatório mensal",
        objective="Resumo",
        schedule="todo dia 15 às 8h",
    )
    result = await _call(env["ctx"], "automation_get", query="relatório")
    assert result["success"] is False
    assert len(result["candidates"]) == 2


@pytest.mark.asyncio
async def test_historico_e_execucao_imediata(env):
    """A execução imediata registra um disparo e o histórico mostra o estado real."""
    created = await _call(
        env["ctx"],
        "automation_create",
        name="Verificação diária",
        objective="Verificar os testes",
        schedule="todos os dias às 9h",
    )
    automation_id = created["automation"]["id"]
    run = await _call(env["ctx"], "automation_run_now", automation_id=automation_id)
    assert run["success"] is True
    assert run["firing"]["state"] in {"pending", "preparing", "running", "completed"}
    assert "run" in run["message"].lower() or "conclu" in run["message"].lower()

    history = await _call(env["ctx"], "automation_history", automation_id=automation_id)
    assert history["count"] == 1
    assert history["firings"][0]["id"] == run["firing"]["id"]


@pytest.mark.asyncio
async def test_teste_nao_dispara_efeito_real(env):
    """O teste verifica a prontidão e não executa a ação."""
    created = await _call(
        env["ctx"],
        "automation_create",
        name="Verificação diária",
        objective="Verificar os testes",
        schedule="todos os dias às 9h",
    )
    automation_id = created["automation"]["id"]
    result = await _call(env["ctx"], "automation_test", automation_id=automation_id)
    assert result["success"] is True
    assert result["executed"] is False
    assert result["readiness"]["ok"] is True
    assert env["session"].query(AutomationModel).one().state == "disabled"


@pytest.mark.asyncio
async def test_suspender_retomar_e_desativar(env):
    """Suspender, retomar (ativar) e desativar percorrem os estados."""
    created = await _call(
        env["ctx"],
        "automation_create",
        name="Verificação diária",
        objective="Verificar os testes",
        schedule="todos os dias às 9h",
    )
    automation_id = created["automation"]["id"]
    token = created["automation"]["confirmation_token"]

    suspended = await _call(env["ctx"], "automation_suspend", automation_id=automation_id)
    assert suspended["automation"]["state"] == "suspended"

    resumed = await _call(
        env["ctx"],
        "automation_enable",
        automation_id=automation_id,
        confirmation_token=token,
    )
    assert resumed["automation"]["state"] == "enabled"

    disabled = await _call(env["ctx"], "automation_disable", automation_id=automation_id)
    assert disabled["automation"]["state"] == "disabled"


@pytest.mark.asyncio
async def test_cancelar_disparos_pendentes(env):
    """Os disparos pendentes são cancelados."""
    created = await _call(
        env["ctx"],
        "automation_create",
        name="Verificação diária",
        objective="Verificar os testes",
        schedule="todos os dias às 9h",
    )
    automation_id = created["automation"]["id"]
    # Um disparo agendado para o futuro fica pendente até o runtime recolhê-lo.
    row = env["session"].query(AutomationModel).one()
    firing = Dispatcher(env["session"]).dispatch_manual(
        row, tag="futuro", scheduled_for=datetime.now(timezone.utc) + timedelta(days=1)
    )
    env["session"].flush()
    assert firing is not None and firing.state == "pending"
    result = await _call(env["ctx"], "automation_cancel", automation_id=automation_id)
    assert result["success"] is True
    assert result["cancelled"] == 1
    env["session"].refresh(firing)
    assert firing.state == "cancelled"


@pytest.mark.asyncio
async def test_estado_do_supervisor_explica_limitacoes(env):
    """O estado do runtime diz o que está e o que não está rodando."""
    result = await _call(env["ctx"], "automation_supervisor_status")
    assert result["success"] is True
    assert result["runtime"]["mode"] in {"runtime_vivo", "servico_nativo", "sem_runtime"}
    assert "limitations" in result["runtime"]


@pytest.mark.asyncio
async def test_ferramenta_sem_sessao_falha_claramente(tmp_path):
    """Fora de um projeto do Callidus, a ferramenta explica o motivo."""
    ctx = ToolContext(project_root=str(tmp_path))
    result = await _call(ctx, "automation_list")
    assert result["success"] is False
    assert "projeto" in result["error"]


# ---------------------------------------------------------------- serviço


@pytest.mark.asyncio
async def test_servico_recusa_projeto_desconhecido(env):
    """Sem projeto, o serviço recusa a criação com o campo indicado."""
    service = AutomationChatService(env["session"], env["settings"])
    with pytest.raises(AutomationChatError) as exc:
        await service.create(
            name="X", objective="Y", schedule="todos os dias às 9h"
        )
    assert exc.value.payload["field"] == "project_id"
