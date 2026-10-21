"""
Arquivo: src/agent/tools/skill_tools.py
Nome: skill_tools.py
Propósito: expor ao agente o ciclo de vida das skills: criar, validar, testar, instalar e ativar.
Responsabilidade: camada de apresentação — handlers das ferramentas de autoria e gestão de skills.
Componentes: register_all, _store, e os handlers de listar, pesquisar, criar, validar, testar, instalar, ativar, desativar, atualizar, histórico e propor.
Dependências: agent.skills.authoring, agent.skills.discovery, agent.tools.registry.
Observações: criar não ativa; instalar não executa; a ativação exige validação.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.skills.authoring import SkillAuthoringService, SkillStore
from agent.skills.discovery import get_skill_registry, installed_skills_dir
from agent.tools.contracts import ExecutionMode, ToolFamily, ToolRisk
from agent.tools.registry import ToolContext, ToolRegistry, ToolSpec

#: Serviço de autoria do processo — o repositório de skills vive em `data/skills`.
SERVICE = SkillAuthoringService(SkillStore(installed_skills_dir()))


def _service() -> SkillAuthoringService:
    """Serviço de autoria, recriado quando a pasta de skills mudou.

    Returns:
        O serviço de autoria em uso.
    """
    global SERVICE
    current = installed_skills_dir()
    if Path(SERVICE.store.root) != current:
        SERVICE = SkillAuthoringService(SkillStore(current))
    return SERVICE


async def _skill_list(ctx: ToolContext, args: dict) -> dict:
    """Lista as skills conhecidas: instaladas, do projeto e do catálogo.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`only_installed` opcional).

    Returns:
        Um dicionário com as skills e a origem de cada uma.
    """
    service = _service()
    installed = service.store.list_installed()
    registry = get_skill_registry(ctx.project_root)
    catalog = [
        {"name": skill.id, "origin": registry.source_of(skill.id) or "catalog", "version": skill.version}
        for skill in registry.list_all()
    ]
    if args.get("only_installed"):
        return {"success": True, "count": len(installed), "skills": [item.as_dict() for item in installed]}
    return {
        "success": True,
        "count": len(installed) + len(catalog),
        "installed": [item.as_dict() for item in installed],
        "catalog": catalog,
    }


async def _skill_search(ctx: ToolContext, args: dict) -> dict:
    """Pesquisa skills por nome, descrição ou palavra-chave.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`query`, `limit` opcional).

    Returns:
        Um dicionário com as skills que casam.
    """
    query = str(args.get("query") or "")
    limit = int(args.get("limit") or 20)
    service = _service()
    hits = service.store.search(query, limit=limit)
    registry = get_skill_registry(ctx.project_root)
    needle = query.strip().lower()
    catalog = []
    if needle:
        for skill in registry.list_all():
            haystack = f"{skill.id} {skill.name} {skill.description} {' '.join(skill.keywords)}".lower()
            if needle in haystack:
                catalog.append({"name": skill.id, "origin": registry.source_of(skill.id) or "catalog"})
    return {
        "success": True,
        "query": query,
        "installed": [item.as_dict() for item in hits],
        "catalog": catalog,
        "count": len(hits) + len(catalog),
    }


async def _skill_create(ctx: ToolContext, args: dict) -> dict:
    """Cria uma skill em estado de rascunho a partir de um pedido.

    A skill criada não é ativada: ela passa por validação e teste antes do uso.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`name`, `description` e listas opcionais).

    Returns:
        Um dicionário com a skill criada.
    """
    result = _service().create_draft(
        str(args.get("name") or ""),
        str(args.get("description") or ""),
        activation=_strings(args.get("activation")),
        prohibited=_strings(args.get("prohibited")),
        tools=_strings(args.get("tools")),
        procedures=_strings(args.get("procedures")),
        validation=_strings(args.get("validation")),
        risks=_strings(args.get("risks")),
        prerequisites=_strings(args.get("prerequisites")),
        requires_binaries=_strings(args.get("requires_binaries")),
        version=str(args.get("version") or "1.0.0"),
    )
    if result.get("success"):
        get_skill_registry(ctx.project_root).reload()
    return result


async def _skill_validate(ctx: ToolContext, args: dict) -> dict:
    """Valida o contrato de uma skill instalada.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`name`).

    Returns:
        Um dicionário com o resultado da validação.
    """
    name = str(args.get("name") or "")
    if not name:
        return {"success": False, "error": "informe o nome da skill"}
    return _service().validate(name)


async def _skill_test(ctx: ToolContext, args: dict) -> dict:
    """Executa os testes de uma skill em ambiente isolado.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`name`).

    Returns:
        Um dicionário com o resultado do teste.
    """
    name = str(args.get("name") or "")
    if not name:
        return {"success": False, "error": "informe o nome da skill"}
    return _service().test(name)


async def _skill_install(ctx: ToolContext, args: dict) -> dict:
    """Instala uma skill a partir de uma pasta externa, sem executar o conteúdo.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`path`, `name` opcional, `force` opcional).

    Returns:
        Um dicionário com a skill instalada.
    """
    path = str(args.get("path") or "")
    if not path:
        return {"success": False, "error": "informe a pasta da skill"}
    result = _service().store.install(
        path,
        name=args.get("name"),
        origin=str(args.get("origin") or "import"),
        state=str(args.get("state") or "draft"),
        force=bool(args.get("force")),
    )
    if result.get("success"):
        get_skill_registry(ctx.project_root).reload()
    return result


async def _skill_activate(ctx: ToolContext, args: dict) -> dict:
    """Ativa uma skill validada.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`name`).

    Returns:
        Um dicionário com o resultado.
    """
    name = str(args.get("name") or "")
    if not name:
        return {"success": False, "error": "informe o nome da skill"}
    result = _service().store.activate(name)
    if result.get("success"):
        get_skill_registry(ctx.project_root).reload()
    return result


async def _skill_deactivate(ctx: ToolContext, args: dict) -> dict:
    """Desativa uma skill sem apagar o conteúdo.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`name`).

    Returns:
        Um dicionário com o resultado.
    """
    name = str(args.get("name") or "")
    if not name:
        return {"success": False, "error": "informe o nome da skill"}
    result = _service().store.deactivate(name)
    if result.get("success"):
        get_skill_registry(ctx.project_root).reload()
    return result


async def _skill_update(ctx: ToolContext, args: dict) -> dict:
    """Atualiza uma skill a partir de uma nova versão, preservando o histórico.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`name`, `path`, `version` opcional).

    Returns:
        Um dicionário com o resultado e a cópia da versão anterior.
    """
    name = str(args.get("name") or "")
    path = str(args.get("path") or "")
    if not name or not path:
        return {"success": False, "error": "informe 'name' e 'path'"}
    result = _service().store.update(name, path, version=args.get("version"))
    if result.get("success"):
        get_skill_registry(ctx.project_root).reload()
    return result


async def _skill_history(ctx: ToolContext, args: dict) -> dict:
    """Mostra o histórico de alterações de uma skill.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`name`).

    Returns:
        Um dicionário com as entradas do histórico.
    """
    name = str(args.get("name") or "")
    if not name:
        return {"success": False, "error": "informe o nome da skill"}
    return _service().store.history(name)


async def _skill_propose(ctx: ToolContext, args: dict) -> dict:
    """Registra uma proposta de melhoria de skill, com a evidência que a motivou.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`skill`, `title`, `rationale`, `changes`, `evidence`).

    Returns:
        Um dicionário com a proposta registrada.
    """
    return _service().propose(
        str(args.get("skill") or ""),
        str(args.get("title") or ""),
        str(args.get("rationale") or ""),
        changes=str(args.get("changes") or ""),
        evidence=_strings(args.get("evidence")),
    )


async def _skill_resolve_proposal(ctx: ToolContext, args: dict) -> dict:
    """Aceita ou rejeita uma proposta de melhoria.

    Args:
        ctx: contexto da ferramenta.
        args: argumentos da chamada (`proposal_id`, `accept`, `note` opcional).

    Returns:
        Um dicionário com a proposta atualizada.
    """
    proposal_id = str(args.get("proposal_id") or "")
    if not proposal_id:
        return {"success": False, "error": "informe o proposal_id"}
    return _service().resolve_proposal(
        proposal_id,
        accept=bool(args.get("accept")),
        note=str(args.get("note") or ""),
    )


def _strings(value: Any) -> list[str]:
    """Normaliza um argumento de lista de textos.

    Args:
        value: valor recebido do modelo.

    Returns:
        A lista de textos; vazia quando o valor não é uma lista.
    """
    if isinstance(value, str):
        return [item.strip() for item in value.split("\n") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def register_all(registry: ToolRegistry) -> None:
    """Registra as ferramentas de ciclo de vida de skills.

    Args:
        registry: registro onde as ferramentas são cadastradas.
    """
    specs = [
        ToolSpec(
            id="skill_list",
            description="Lista as skills instaladas e do catálogo, com a origem de cada uma",
            input_schema={"only_installed": "bool?"},
            family=ToolFamily.SKILL.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'count'",
        ),
        ToolSpec(
            id="skill_search",
            description="Pesquisa skills por nome, descrição ou palavra-chave",
            input_schema={"query": "str", "limit": "int?"},
            family=ToolFamily.SKILL.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'count'",
        ),
        ToolSpec(
            id="skill_create",
            description="Cria uma skill em rascunho (não ativa; exige validação e teste)",
            input_schema={
                "name": "str",
                "description": "str",
                "activation": "list[str]?",
                "prohibited": "list[str]?",
                "tools": "list[str]?",
                "procedures": "list[str]?",
                "validation": "list[str]?",
                "risks": "list[str]?",
                "prerequisites": "list[str]?",
                "requires_binaries": "list[str]?",
                "version": "str?",
            },
            family=ToolFamily.SKILL.value,
            risk=ToolRisk.WRITE.value,
            requires_approval=True,
            permissions=["fs.write"],
            side_effects=True,
            execution=ExecutionMode.FOREGROUND.value,
            verify="depois valide com skill_validate",
        ),
        ToolSpec(
            id="skill_validate",
            description="Valida o contrato de uma skill instalada",
            input_schema={"name": "str"},
            family=ToolFamily.SKILL.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'valid'",
        ),
        ToolSpec(
            id="skill_test",
            description="Executa os testes de uma skill em ambiente isolado",
            input_schema={"name": "str"},
            family=ToolFamily.SKILL.value,
            risk=ToolRisk.EXECUTE.value,
            requires_approval=True,
            permissions=["process.spawn"],
            side_effects=True,
            execution=ExecutionMode.FOREGROUND.value,
            hard_timeout_seconds=180,
            verify="confira o campo 'status'",
        ),
        ToolSpec(
            id="skill_install",
            description="Instala uma skill de uma pasta externa (não executa o conteúdo)",
            input_schema={"path": "str", "name": "str?", "force": "bool?", "origin": "str?", "state": "str?"},
            family=ToolFamily.SKILL.value,
            risk=ToolRisk.WRITE.value,
            requires_approval=True,
            permissions=["fs.write"],
            side_effects=True,
            execution=ExecutionMode.FOREGROUND.value,
            verify="depois valide com skill_validate",
        ),
        ToolSpec(
            id="skill_activate",
            description="Ativa uma skill validada para uso pelo agente",
            input_schema={"name": "str"},
            family=ToolFamily.SKILL.value,
            risk=ToolRisk.WRITE.value,
            requires_approval=True,
            permissions=["fs.write"],
            side_effects=True,
            execution=ExecutionMode.FOREGROUND.value,
            verify="confira o campo 'skill.state'",
        ),
        ToolSpec(
            id="skill_deactivate",
            description="Desativa uma skill sem apagar o conteúdo",
            input_schema={"name": "str"},
            family=ToolFamily.SKILL.value,
            risk=ToolRisk.WRITE.value,
            requires_approval=True,
            permissions=["fs.write"],
            side_effects=True,
            execution=ExecutionMode.FOREGROUND.value,
            verify="confira o campo 'skill.enabled'",
        ),
        ToolSpec(
            id="skill_update",
            description="Atualiza uma skill preservando o histórico e a versão anterior",
            input_schema={"name": "str", "path": "str", "version": "str?"},
            family=ToolFamily.SKILL.value,
            risk=ToolRisk.WRITE.value,
            requires_approval=True,
            permissions=["fs.write"],
            side_effects=True,
            execution=ExecutionMode.FOREGROUND.value,
            verify="confira o campo 'backup'",
        ),
        ToolSpec(
            id="skill_history",
            description="Histórico de alterações de uma skill",
            input_schema={"name": "str"},
            family=ToolFamily.SKILL.value,
            risk=ToolRisk.READ.value,
            execution=ExecutionMode.NON_INTERACTIVE.value,
            verify="confira o campo 'count'",
        ),
        ToolSpec(
            id="skill_propose",
            description="Registra uma proposta de melhoria de skill com a evidência que a motivou",
            input_schema={"skill": "str", "title": "str", "rationale": "str", "changes": "str?", "evidence": "list[str]?"},
            family=ToolFamily.SKILL.value,
            risk=ToolRisk.WRITE.value,
            requires_approval=True,
            permissions=["fs.write"],
            side_effects=True,
            execution=ExecutionMode.FOREGROUND.value,
            verify="confira o campo 'proposal.state'",
        ),
        ToolSpec(
            id="skill_resolve_proposal",
            description="Aceita ou rejeita uma proposta de melhoria de skill",
            input_schema={"proposal_id": "str", "accept": "bool", "note": "str?"},
            family=ToolFamily.SKILL.value,
            risk=ToolRisk.WRITE.value,
            requires_approval=True,
            permissions=["fs.write"],
            side_effects=True,
            execution=ExecutionMode.FOREGROUND.value,
            verify="confira o campo 'proposal.state'",
        ),
    ]
    handlers = {
        "skill_list": _skill_list,
        "skill_search": _skill_search,
        "skill_create": _skill_create,
        "skill_validate": _skill_validate,
        "skill_test": _skill_test,
        "skill_install": _skill_install,
        "skill_activate": _skill_activate,
        "skill_deactivate": _skill_deactivate,
        "skill_update": _skill_update,
        "skill_history": _skill_history,
        "skill_propose": _skill_propose,
        "skill_resolve_proposal": _skill_resolve_proposal,
    }
    for spec in specs:
        registry.register(spec, handlers[spec.id])


__all__ = ["SERVICE", "register_all"]
