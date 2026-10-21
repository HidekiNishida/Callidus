"""
Arquivo: tests/test_tool_contracts.py
Nome: test_tool_contracts.py
Propósito: verificar o contrato unificado das ferramentas: risco, permissões, disponibilidade, prazo e cancelamento.
Responsabilidade: camada de testes — comportamento do registro, da política e da sondagem de requisitos.
Componentes: ToolSpec, ToolRegistry.execute, PermissionPolicy, check_requirements, redact.
Dependências: agent.tools.registry, agent.tools.policy, agent.tools.availability, pytest.
Observações: os testes usam ferramentas registradas no próprio teste, sem tocar o sistema.
"""
import asyncio

import pytest

from agent.tools.availability import check_requirements
from agent.tools.contracts import ToolRisk, risk_at_least
from agent.tools.policy import PermissionPolicy, redact, redact_text
from agent.tools.registry import ToolContext, ToolRegistry, ToolSpec


def _registry_with(spec: ToolSpec, handler) -> ToolRegistry:
    """Registro com uma única ferramenta, para isolar o comportamento testado.

    Args:
        spec: contrato da ferramenta.
        handler: handler assíncrono da ferramenta.

    Returns:
        O registro pronto para uso.
    """
    reg = ToolRegistry()
    reg.register(spec, handler)
    return reg


@pytest.mark.asyncio
async def test_ferramenta_indisponivel_e_recusada_com_dica():
    """A ferramenta cujo pré-requisito falta é recusada antes do handler, com a dica de resolução."""
    calls: list[int] = []

    async def handler(ctx, args):
        calls.append(1)
        return {"success": True}

    reg = _registry_with(
        ToolSpec(id="needs_binary", description="x", requires=["binary:definitely-not-installed-xyz"]),
        handler,
    )
    out = await reg.execute("needs_binary", ToolContext(project_root="."), {})
    assert out["success"] is False
    assert out["error"] == "requisitos ausentes"
    assert out["missing"] == ["binary:definitely-not-installed-xyz"]
    assert out["hints"]
    assert calls == []


@pytest.mark.asyncio
async def test_ferramenta_inexistente_lista_as_conhecidas():
    """O erro de ferramenta desconhecida diz quais ids existem."""
    reg = ToolRegistry()
    out = await reg.execute("nao_existe", ToolContext(project_root="."), {})
    assert out["success"] is False
    assert "ferramenta desconhecida" in out["error"]


@pytest.mark.asyncio
async def test_aprovacao_obrigatoria_recusa_sem_aprovacao():
    """Uma ferramenta que exige aprovação não roda sem a aprovação explícita."""
    ran: list[bool] = []

    async def handler(ctx, args):
        ran.append(True)
        return {"success": True}

    reg = _registry_with(ToolSpec(id="perigosa", description="x", requires_approval=True), handler)
    out = await reg.execute("perigosa", ToolContext(project_root="."), {})
    assert out["error"] == "approval_required"
    assert ran == []
    out = await reg.execute("perigosa", ToolContext(project_root="."), {}, approved=True)
    assert out["success"] is True
    assert ran == [True]


@pytest.mark.asyncio
async def test_politica_bloqueia_familia_desligada():
    """Uma família desligada na política recusa todas as suas ferramentas."""
    ran: list[bool] = []

    async def handler(ctx, args):
        ran.append(True)
        return {"success": True}

    reg = _registry_with(
        ToolSpec(id="system_x", description="x", family="system", risk=ToolRisk.READ.value),
        handler,
    )
    policy = PermissionPolicy()
    policy.disable_family("system")
    ctx = ToolContext(project_root=".", policy=policy)
    out = await reg.execute("system_x", ctx, {})
    assert out["success"] is False
    assert out["error"] == "bloqueado pela política"
    assert ran == []


@pytest.mark.asyncio
async def test_politica_exige_aprovacao_acima_do_piso():
    """Ferramenta de risco alto pede aprovação quando o piso automático é menor."""
    ran: list[bool] = []

    async def handler(ctx, args):
        ran.append(True)
        return {"success": True}

    reg = _registry_with(
        ToolSpec(id="exec_x", description="x", family="command", risk=ToolRisk.EXECUTE.value),
        handler,
    )
    policy = PermissionPolicy(max_auto_risk=ToolRisk.READ)
    ctx = ToolContext(project_root=".", policy=policy)
    out = await reg.execute("exec_x", ctx, {})
    assert out["error"] == "approval_required"
    assert ran == []


@pytest.mark.asyncio
async def test_prazo_imposto_corta_a_execucao():
    """O prazo duro interrompe a ferramenta e devolve erro controlado."""
    async def handler(ctx, args):
        await asyncio.sleep(2)
        return {"success": True}

    reg = _registry_with(
        ToolSpec(id="lenta", description="x", hard_timeout_seconds=0.05),
        handler,
    )
    out = await reg.execute("lenta", ToolContext(project_root="."), {})
    assert out["success"] is False
    assert out["error"] == "tempo limite excedido"


@pytest.mark.asyncio
async def test_cancelamento_cooperativo_impede_a_execucao():
    """Com o evento de cancelamento ligado, a ferramenta nem começa."""
    ran: list[bool] = []

    async def handler(ctx, args):
        ran.append(True)
        return {"success": True}

    reg = _registry_with(ToolSpec(id="cancelavel", description="x"), handler)
    event = asyncio.Event()
    event.set()
    ctx = ToolContext(project_root=".", cancel_event=event)
    out = await reg.execute("cancelavel", ctx, {})
    assert out["success"] is False
    assert out["error"] == "cancelado"
    assert ran == []


@pytest.mark.asyncio
async def test_segredo_na_saida_e_redigido():
    """O resultado da ferramenta tem os segredos redigidos antes de voltar ao modelo."""
    async def handler(ctx, args):
        return {"success": True, "stdout": "export API_KEY=abcdef123456"}

    reg = _registry_with(ToolSpec(id="com_segredo", description="x"), handler)
    out = await reg.execute("com_segredo", ToolContext(project_root="."), {})
    assert "abcdef123456" not in out["stdout"]
    assert "[REDACTED]" in out["stdout"]


def test_catalogo_compacto_e_uma_linha_por_ferramenta():
    """O catálogo compacto lista uma linha por ferramenta, com a família em ordem."""
    reg = ToolRegistry()
    reg.register(ToolSpec(id="a", description="primeira", input_schema={"x": "str"}), None)
    reg.register(ToolSpec(id="b", description="segunda", family="system"), None)
    catalog = reg.compact_catalog()
    assert len(catalog.splitlines()) == 2
    assert "a: primeira (args: x)" in catalog
    assert reg.compact_catalog(["system"]) == "- b: segunda"


def test_describe_carrega_o_detalhe_sob_demanda():
    """A descrição completa traz contrato, risco e disponibilidade de uma ferramenta."""
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            id="x",
            description="d",
            risk=ToolRisk.EXECUTE.value,
            permissions=["process.spawn"],
            requires=["binary:nao-existe-xyz"],
            verify="confira o processo",
        ),
        None,
    )
    out = reg.describe("x")
    assert out["success"] is True
    assert out["risk"] == "execute"
    assert out["permissions"] == ["process.spawn"]
    assert out["available"] is False
    assert out["missing"] == ["binary:nao-existe-xyz"]


def test_verificacao_de_requisitos_reconhece_os_tipos():
    """Cada tipo de requisito é verificado pelo seu próprio mecanismo."""
    result = check_requirements(["os:macos,linux", "binary:python3", "module:json"])
    assert "os:macos,linux" not in result.missing
    assert "module:json" not in result.missing


def test_ordem_de_risco_e_comparavel():
    """A ordem de risco permite comparar níveis sem depender do enum."""
    assert risk_at_least(ToolRisk.PRIVILEGED, ToolRisk.EXECUTE)
    assert not risk_at_least(ToolRisk.READ, ToolRisk.WRITE)
    assert risk_at_least(ToolRisk.READ, ToolRisk.READ)


def test_piso_de_risco_autoriza_o_proprio_nivel():
    """O piso de risco automático autoriza o nível do piso e recusa o seguinte."""
    policy = PermissionPolicy(max_auto_risk=ToolRisk.WRITE)
    dentro = policy.decide("t", risk=ToolRisk.WRITE)
    assert dentro.allowed is True
    assert dentro.requires_approval is False
    acima = policy.decide("t", risk=ToolRisk.EXECUTE)
    assert acima.allowed is True
    assert acima.requires_approval is True


def test_redacao_de_texto_remove_credenciais():
    """A redação encontra credenciais em texto livre."""
    text = "conectando com api_key=sk-1234567890abcd e Authorization: Bearer xyz98765"
    redacted = redact_text(text)
    assert "sk-1234567890abcd" not in redacted
    assert "xyz98765" not in redacted
    assert "[REDACTED]" in redacted


def test_redacao_preserva_a_forma_dos_dados():
    """A redação percorre dicionários e listas sem mudar a estrutura."""
    payload = {"a": ["token=abcdefgh12345", 1], "b": {"c": "password=xyzxyz12"}}
    out = redact(payload)
    assert out["a"][1] == 1
    assert "abcdefgh12345" not in out["a"][0]
    assert "xyzxyz12" not in out["b"]["c"]
