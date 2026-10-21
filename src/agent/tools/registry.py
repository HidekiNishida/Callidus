"""
Arquivo: src/agent/tools/registry.py
Nome: registry.py
Propósito: manter o registro central das ferramentas do agente e executá-las com contrato uniforme.
Responsabilidade: camada de aplicação — catálogo de ferramentas, aliases e despacho das chamadas.
Componentes: ToolSpec, ToolContext, ToolRegistry, canonical_tool_id, current_call_id, build_default_registry, TOOL_ALIASES.
Dependências: agent.observability, pydantic.
Observações: ferramentas que exigem aprovação recusam a execução quando ela não foi concedida.
"""
from __future__ import annotations

import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from agent.observability import emit


class ToolSpec(BaseModel):
    """Contrato de uma ferramenta exposta ao modelo.

    Atributos:
        id: identificador da ferramenta, como o modelo a chama.
        description: descrição enviada ao modelo.
        input_schema: schema JSON dos argumentos aceitos.
        requires_approval: quando `True`, a execução exige aprovação explícita.
        timeout_seconds: tempo limite sugerido para a execução.
    """

    id: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False
    timeout_seconds: float = 60.0


@dataclass
class ToolContext:
    """Contexto handed a uma ferramenta durante a execução.

    Atributos:
        project_root: raiz autorizada do projeto.
        run_id: run em curso, quando houver.
        task_id: tarefa em execução, quando houver.
        memory_saver: callback opcional para gravar memória.
        browser_mode: modo do navegador (`off` por padrão).
        remote: configuração do computador remoto, quando o projeto roda em outro servidor.
        session: sessão do banco da execução, quando a ferramenta precisar do estado persistente.
        project_id: projeto da conversa, para as ferramentas que pertencem a um projeto.
        conversation_id: conversa em curso, para as ferramentas que pertencem a uma conversa.
        settings: configurações do processo, para as ferramentas que dependem delas.
    """

    project_root: str
    run_id: str | None = None
    task_id: str | None = None
    memory_saver: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    browser_mode: str = "off"
    # Configuração do computador remoto (quando o projeto roda em outro servidor).
    remote: Any = None
    # Sessão do banco da execução: as ferramentas que consultam o estado persistente
    # (as automações) usam os serviços, e não HTTP contra a própria API.
    session: Any = None
    project_id: str | None = None
    conversation_id: str | None = None
    settings: Any = None


ToolHandler = Callable[[ToolContext, dict[str, Any]], Awaitable[dict[str, Any]]]

# Nomes que o modelo costuma inventar → ferramenta real.
TOOL_ALIASES: dict[str, str] = {
    "ls": "list_dir",
    "list_files": "list_dir",
    "list_directory": "list_dir",
    "dir": "list_dir",
    "glob": "glob_files",
    "find_files": "glob_files",
    "find": "glob_files",
    "grep": "search_grep",
    "search": "search_grep",
    "str_replace": "edit_file",
    "search_replace": "edit_file",
    "apply_patch": "edit_file",
    "replace_in_file": "edit_file",
    "edit": "edit_file",
    "delete": "delete_file",
    "remove_file": "delete_file",
    "rm": "delete_file",
    "shell": "run_command",
    "bash": "run_command",
    "exec": "run_command",
    "python": "run_script",
    "pytest": "run_pytest",
    "mkdir": "make_dir",
    "create_directory": "make_dir",
    "mv": "move_file",
    "rename": "move_file",
    "git": "git_status",
    "browse": "browser",
    "web": "browser",
    "open_url": "browser",
    "sysinfo": "system_info",
    "os_info": "system_info",
    "whoami": "system_info",
}


def canonical_tool_id(tool_id: str) -> str:
    """Resolve o alias de uma ferramenta para o identificador real.

    Args:
        tool_id: nome pedido pelo modelo.

    Returns:
        O identificador canônico; o próprio nome quando não há alias.
    """
    return TOOL_ALIASES.get(tool_id, tool_id)


class ToolRegistry:
    """Catálogo de ferramentas do agente: specs, handlers e execução uniformizada.

    Atributos:
        _specs: especificações registradas, indexadas pelo identificador.
        _handlers: handlers registrados, indexados pelo identificador.
    """

    def __init__(self) -> None:
        """Cria um registro vazio."""
        self._specs: dict[str, ToolSpec] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        """Registra uma ferramenta e seu handler.

        Args:
            spec: contrato da ferramenta.
            handler: função assíncrona que executa a ferramenta.
        """
        self._specs[spec.id] = spec
        self._handlers[spec.id] = handler

    def get_spec(self, tool_id: str) -> ToolSpec:
        """Especificação de uma ferramenta.

        Args:
            tool_id: identificador da ferramenta.

        Returns:
            A `ToolSpec` correspondente.

        Raises:
            KeyError: quando a ferramenta não está registrada.
        """
        if tool_id not in self._specs:
            raise KeyError(tool_id)
        return self._specs[tool_id]

    def list_specs(self) -> list[ToolSpec]:
        """Todas as especificações registradas.

        Returns:
            Uma cópia da lista de specs.
        """
        return list(self._specs.values())

    async def execute(
        self,
        tool_id: str,
        ctx: ToolContext,
        args: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        """Executa uma ferramenta e emite os eventos de início e de desfecho.

        Args:
            tool_id: nome pedido pelo modelo; aliases são resolvidos.
            ctx: contexto handed à ferramenta.
            args: argumentos da chamada.
            approved: quando `True`, ferramentas que exigem aprovação são executadas mesmo assim.

        Returns:
            O resultado da ferramenta; em caso de recusa ou erro, um dicionário com `success` falso.

        Raises:
            Exception: qualquer erro levantado pelo handler é propagado após o evento de falha.
        """
        tool_id = canonical_tool_id(tool_id)
        if tool_id not in self._specs:
            known = ", ".join(sorted(self._specs))
            emit(
                "tool.failed",
                {"call_id": uuid.uuid4().hex[:12], "tool": tool_id, "error": "ferramenta desconhecida", "executed": False},
            )
            return {"success": False, "error": f"ferramenta desconhecida: {tool_id}", "known": known}
        spec = self.get_spec(tool_id)
        if spec.requires_approval and not approved:
            emit(
                "tool.failed",
                {"call_id": uuid.uuid4().hex[:12], "tool": tool_id, "error": "approval_required", "executed": False},
            )
            return {
                "success": False,
                "error": "approval_required",
                "tool": tool_id,
            }
        handler = self._handlers[tool_id]
        call_id = uuid.uuid4().hex[:12]
        token = _CALL_ID.set(call_id)
        started = time.monotonic()
        emit("tool.started", {"call_id": call_id, "tool": tool_id, "args": _args_preview(args)}, commit=True)
        try:
            result = await handler(ctx, args)
        except Exception as exc:
            emit(
                "tool.failed",
                {"call_id": call_id, "tool": tool_id, "error": f"{type(exc).__name__}: {exc}", "duration_ms": _ms(started)},
            )
            raise
        finally:
            _CALL_ID.reset(token)
        if result.get("success"):
            emit("tool.completed", {"call_id": call_id, "tool": tool_id, "duration_ms": _ms(started), "summary": _summary(result)})
        else:
            emit(
                "tool.failed",
                {
                    "call_id": call_id,
                    "tool": tool_id,
                    "error": str(result.get("error") or "falhou"),
                    "duration_ms": _ms(started),
                    "summary": _summary(result),
                },
            )
        return result


_CALL_ID: ContextVar[str | None] = ContextVar("tool_call_id", default=None)
_PREVIEW_KEYS = ("content", "new_string", "old_string", "new", "old", "replace", "replacement")


def current_call_id() -> str | None:
    """Id da chamada de ferramenta em andamento (comandos e arquivos usam o mesmo para se ligar a ela)."""
    return _CALL_ID.get()


def _ms(started: float) -> int:
    """Duração em milissegundos desde o instante informado.

    Args:
        started: instante de início, medido com `time.monotonic`.

    Returns:
        Os milissegundos decorridos.
    """
    return int((time.monotonic() - started) * 1000)


def _args_preview(args: dict[str, Any]) -> dict[str, Any]:
    """Argumentos para exibição: conteúdo de arquivo vira tamanho (o diff real sai em `file.*`)."""
    out: dict[str, Any] = {}
    for key, value in args.items():
        if key in _PREVIEW_KEYS and isinstance(value, str) and len(value) > 200:
            out[key] = f"[{len(value)} caracteres]"
        else:
            out[key] = value
    return out


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    """Campos do resultado que valem a pena exibir no evento de desfecho.

    Args:
        result: resultado devolvido pela ferramenta.

    Returns:
        Um dicionário apenas com os campos presentes entre os conhecidos.
    """
    keep = ("path", "exit_code", "count", "bytes", "added", "removed", "replacements", "total_lines", "truncated", "category")
    return {k: result[k] for k in keep if k in result}


def build_default_registry() -> ToolRegistry:
    """Monta o registro com todas as ferramentas embutidas.

    Returns:
        O registro pronto para uso, com as ferramentas de `agent.tools.builtins` e
        `agent.tools.automations` cadastradas.
    """
    from agent.tools import automations as automation_tools
    from agent.tools import builtins as built

    reg = ToolRegistry()
    built.register_all(reg)
    automation_tools.register_all(reg)
    return reg
