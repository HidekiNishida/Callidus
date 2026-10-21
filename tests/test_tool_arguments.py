"""
Arquivo: tests/test_tool_arguments.py
Nome: test_tool_arguments.py
Propósito: verificar a validação de argumentos antes da execução de uma ferramenta.
Responsabilidade: camada de testes — tipos, obrigatoriedade e recusa no registro.
Componentes: validate_arguments, ToolRegistry.execute.
Dependências: agent.tools.arguments, agent.tools.registry, pytest.
Observações: a recusa acontece antes do handler, então nenhuma ferramenta chega a rodar.
"""
import pytest

from agent.tools.arguments import validate_arguments
from agent.tools.registry import ToolContext, build_default_registry


def test_atalho_exige_campo_e_aceita_opcional_ausente():
    """Campo obrigatório ausente falha; campo opcional ausente passa."""
    schema = {"path": "str", "limit": "int?"}
    assert validate_arguments(schema, {}) == "argumento obrigatório ausente: path"
    assert validate_arguments(schema, {"path": "a.py"}) is None


def test_atalho_recusa_tipo_errado_e_bool_no_lugar_de_int():
    """Um booleano não satisfaz um inteiro, mesmo sendo subclasse de int em Python."""
    assert validate_arguments({"pid": "int"}, {"pid": True}) == "argumento pid deve ser int"
    assert validate_arguments({"pid": "int"}, {"pid": 12}) is None


def test_uniao_aceita_texto_ou_lista_de_texto():
    """O comando pode chegar como texto ou como lista, como o handler já executa."""
    schema = {"command": "str|list[str]"}
    assert validate_arguments(schema, {"command": "pytest -q"}) is None
    assert validate_arguments(schema, {"command": ["pytest", "-q"]}) is None
    assert validate_arguments(schema, {"command": ["pytest", 1]}) == "argumento command deve ser str|list[str]"


def test_literal_restringe_o_valor():
    """Um campo enumerado só aceita os literais declarados."""
    schema = {"scope": "project|conversation"}
    assert validate_arguments(schema, {"scope": "project"}) is None
    assert "scope" in (validate_arguments(schema, {"scope": "global"}) or "")


def test_json_schema_exige_obrigatorios_e_enum():
    """O esquema das automações recusa campo obrigatório ausente e valor fora do enum."""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "action_kind": {"type": "string", "enum": ["callidus", "script"]},
            "command": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["name"],
    }
    assert validate_arguments(schema, {}) == "argumento obrigatório ausente: name"
    assert validate_arguments(schema, {"name": "diária", "action_kind": "shell"}) == "argumento action_kind deve ser um de: callidus, script"
    assert validate_arguments(schema, {"name": "diária", "command": ["pytest"]}) is None


@pytest.mark.asyncio
async def test_registro_recusa_argumento_invalido_sem_executar(tmp_path):
    """O registro devolve erro estável e não chama o handler."""
    registry = build_default_registry()
    out = await registry.execute("read_file", ToolContext(project_root=str(tmp_path)), {})
    assert out["success"] is False
    assert out["code"] == "invalid_arguments"
    assert "path" in out["error"]


@pytest.mark.asyncio
async def test_registro_aceita_comando_em_texto_na_validacao(tmp_path):
    """A validação não rejeita o texto que run_command já sabe dividir — a execução segue exigindo aprovação."""
    registry = build_default_registry()
    out = await registry.execute(
        "run_command",
        ToolContext(project_root=str(tmp_path)),
        {"command": "echo ok"},
    )
    assert out["error"] == "approval_required"
