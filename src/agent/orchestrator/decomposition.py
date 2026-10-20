# src/agent/orchestrator/decomposition.py — decomposição hierárquica
from __future__ import annotations

import re
import uuid
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agent.config import Settings
from agent.domain.enums import TaskKind, TaskStatus
from agent.domain.schemas import TaskCreate, TaskDependencyCreate, TaskStatusUpdate
from agent.providers.base import LLMProvider, ModelProfile
from agent.context.budget import ContextComponent, assemble_messages
from agent.providers.base import ChatCompletionRequest
from agent.providers.registry import build_provider_by_name
from agent.services.task_service import DependencyError, TaskService
from agent.services.agent_service import AgentService
from agent.guides.discover import capability_line, guide_digest
from agent.i18n.locale import detect_language, language_instruction
from agent.tools.builtins import TOOL_CATALOG
from agent.util.json_parse import parse_json_object


class SubTaskSpec(BaseModel):
    title: str
    objective: str
    kind: TaskKind = TaskKind.OPERATION
    scope: str | None = None
    acceptance_criteria: str | None = None
    metadata: dict[str, Any] | None = None
    depends_on_indices: list[int] = Field(default_factory=list)


class DecompositionResult(BaseModel):
    subtasks: list[SubTaskSpec]


BUILTIN_E2E_PLAN = DecompositionResult(
    subtasks=[
        SubTaskSpec(
            title="Inspecionar projeto",
            objective="Listar arquivos relevantes do projeto de teste",
            metadata={"tool": "search_grep", "tool_args": {"pattern": "def "}},
        ),
        SubTaskSpec(
            title="Corrigir implementação",
            objective="Corrigir bug em calc.py conforme critérios",
            metadata={
                "tool": "write_file",
                "tool_args": {
                    "path": "calc.py",
                    "content": "def add(a: int, b: int) -> int:\n    return a + b\n",
                },
            },
            depends_on_indices=[0],
        ),
        SubTaskSpec(
            title="Verificar testes",
            objective="Executar pytest no fixture",
            metadata={"verification": {"type": "pytest", "path": "tests"}},
            depends_on_indices=[1],
        ),
    ]
)

GENERIC_TEMPLATE = DecompositionResult(
    subtasks=[
        SubTaskSpec(
            title="Inspecionar código",
            objective="Buscar símbolos e arquivos relacionados ao objetivo",
            metadata={"tool": "list_dir", "tool_args": {"path": "."}},
        ),
        SubTaskSpec(
            title="Aplicar alterações",
            objective="Implementar a mudança pedida no objetivo pai",
            metadata={"model_operation": True, "prompt_key": "implement"},
            depends_on_indices=[0],
        ),
        SubTaskSpec(
            title="Verificar",
            objective="Executar testes do projeto",
            metadata={"verification": {"type": "pytest", "path": "."}},
            depends_on_indices=[1],
        ),
    ]
)


async def plan_with_model(
    provider: LLMProvider,
    profile: ModelProfile,
    objective: str,
    context_snippet: str,
    *,
    language: str = "pt",
    browser_mode: str = "off",
    requirements: list[dict[str, Any]] | None = None,
    project_root: str = "",
) -> DecompositionResult | None:
    """Plano do modelo.

    O modelo recebe as ferramentas de **inspeção**: um modelo que trabalha com ferramentas
    (o `gpt-oss:20b`) devolve resposta vazia quando o pedido chega sem elas, e o plano caía no
    template genérico — que perde a especificidade do objetivo. Aqui ele pode ler o projeto
    antes de responder com o JSON do plano.
    """
    browser_line = (
        "O navegador está ligado. Use browser para pesquisa, checagem, demonstração ou teste. "
        "action: search, navigate, snapshot, click, type, press, scroll ou close."
        if browser_mode in {"headless", "visible"}
        else "O navegador está desligado. Não use a ferramenta browser."
    )
    prompt = (
        f"{language_instruction(language)}\n{browser_line}\n"
        f"Objetivo: {objective}\n\nContexto do projeto:\n{context_snippet}\n\n"
        f"{requirements_block(requirements)}"
        "Decomponha TODAS as etapas, do entendimento do pedido até a verificação e a conclusão.\n"
        "A última subtarefa deve ser a resposta final ao usuário "
        '(metadata.final_answer=true e metadata.model_operation=true). '
        "Antes dela, inclua uma verificação concreta (pytest, script, command ou file_contains).\n"
        f"{capability_line(profile.model_id)}\n"
        f"{TOOL_CATALOG}\n"
        "Cada subtarefa de ferramenta usa metadata.tool com um id real e metadata.tool_args. "
        "Para editar código use edit_file, não reescreva o arquivo inteiro. "
        "Para explorar use list_dir ou glob_files. Para teste Python use run_pytest ou run_script. "
        "Verificação pode ser metadata.verification com type pytest, script ou command.\n"
        'Responda SOMENTE JSON válido: {"subtasks":[{"title":"...","objective":"...",'
        '"kind":"operation","metadata":{"tool":"read_file","tool_args":{"path":"..."}},'
        '"depends_on_indices":[]}]}'
    )
    budget = assemble_messages(
        profile,
        [ContextComponent(name="decomposição", text=prompt, required=True, priority=100)],
    )
    from agent.orchestrator.tool_loop import INSPECTION_TOOLS, run_tool_loop
    from agent.tools.registry import ToolContext, build_default_registry

    content = ""
    if getattr(provider, "capabilities", None) and _supports_tool_loop(provider):
        outcome = await run_tool_loop(
            provider=provider,
            messages=budget.messages,
            profile=profile,
            registry=build_default_registry(),
            ctx=ToolContext(project_root=project_root or "."),
            tool_ids=INSPECTION_TOOLS,
            final_tools=INSPECTION_TOOLS,
            final_tools_after=(),
            final_instruction=(
                "Você já inspecionou o que era preciso. Responda agora com o JSON do plano "
                "no formato pedido."
            ),
            final_instruction_after=(
                "Agora responda apenas com o JSON do plano. Não peça mais ferramentas."
            ),
            purpose="plan",
        )
        content = outcome.content or ""
    else:
        from agent.providers.observed import observed_chat

        resp = await observed_chat(
            provider, ChatCompletionRequest(messages=budget.messages, profile=profile), purpose="plan"
        )
        content = resp.content or ""
    data, err = parse_json_object(content)
    if err or not data:
        return None
    try:
        plan = DecompositionResult.model_validate(data)
        return plan if plan.subtasks else None
    except Exception:
        return None


def _supports_tool_loop(provider) -> bool:
    """O provedor sabe manter a conversa de ferramentas? (mesma regra do orquestrador.)"""
    capabilities = getattr(provider, "capabilities", None)
    if not callable(capabilities):
        return False
    try:
        return bool(capabilities().tool_loop)
    except Exception:  # pragma: no cover - provedor de teste sem capacidades
        return False


def requirements_block(requirements: list[dict[str, Any]] | None) -> str:
    """Requisitos que o plano precisa cobrir; cada subtarefa declara em metadata.covers os que atende."""
    if not requirements:
        return ""
    lines = [
        f"- {r['id']}: {r['description']}" + (f" (parte: {r['part']})" if r.get("part") else "")
        for r in requirements
    ]
    return (
        "Requisitos obrigatórios desta etapa (nenhum pode ficar de fora nem virar opcional):\n"
        + "\n".join(lines)
        + '\nCada subtarefa declara metadata.covers com os ids que atende, por exemplo ["R1"]; '
        'se atende só uma parte, {"req":"R1","partial":true,"part":"..."}. '
        "Todo requisito precisa de ao menos uma subtarefa com verificação concreta.\n\n"
    )


_CHANGE_REQUEST = re.compile(
    r"\b(arquiv|código|codigo|implement|cri[ae]|corrig|bug|teste|refactor|fun[cç]|classe|pasta|diret[oó]ri|edite|script|módulo|modulo)\b",
    re.IGNORECASE,
)
_QUESTION = re.compile(
    r"^(que|qual|quais|quando|onde|quem|como|por que|porque|me diga|me fala|what|when|where|who|how)\b",
    re.IGNORECASE,
)
_PAGE_REQUEST = re.compile(r"\b(site|p[aá]gina|html|landing|website|loja)\b", re.IGNORECASE)


def _is_page_request(objective: str) -> bool:
    text = objective or ""
    return _PAGE_REQUEST.search(text) is not None and ".py" not in text.lower()


def page_plan(objective: str) -> DecompositionResult:
    """Página ou site: escrever o HTML e conferir o arquivo, sem pytest."""
    order = " ".join((objective or "").strip().split())
    return DecompositionResult(
        subtasks=[
            SubTaskSpec(
                title="Ver a pasta",
                objective="Listar o que já existe na pasta do projeto",
                metadata={"tool": "list_dir", "tool_args": {"path": "."}, "atomic": True},
            ),
            SubTaskSpec(
                title="Escrever a página",
                objective=(
                    f"{order}\n\n"
                    "Grave index.html completo, no idioma do pedido, com cabeçalho, seções e um chamado para ação. "
                    "O estilo fica no próprio arquivo."
                ),
                metadata={"model_operation": True, "atomic": True, "prompt_key": "page"},
                depends_on_indices=[0],
            ),
            SubTaskSpec(
                title="Conferir a página",
                objective="index.html precisa existir e ter a estrutura HTML.",
                metadata={
                    "verification": {"type": "file_contains", "path": "index.html", "contains": "<html"},
                    "atomic": True,
                },
                depends_on_indices=[1],
            ),
        ]
    )


def align_verification(objective: str, plan: DecompositionResult) -> DecompositionResult:
    """Pedido de página não herda a verificação de pytest do plano genérico."""
    if not _is_page_request(objective):
        return plan
    subtasks: list[SubTaskSpec] = []
    changed = False
    for spec in plan.subtasks:
        meta = dict(spec.metadata or {})
        verification = meta.get("verification")
        if isinstance(verification, dict) and verification.get("type") == "pytest":
            meta["verification"] = {"type": "file_contains", "path": "index.html", "contains": "<html"}
            changed = True
        if meta.get("model_operation") and not meta.get("final_answer"):
            meta["prompt_key"] = "page"
            meta["atomic"] = True
            changed = True
        subtasks.append(spec.model_copy(update={"metadata": meta}) if changed else spec)
    return DecompositionResult(subtasks=subtasks) if changed else plan


def fallback_plan(objective: str) -> tuple[DecompositionResult, str]:
    """Plano genérico, mas **com o objetivo concreto**: a etapa que aplica a alteração recebe o
    pedido do pai, senão o modelo recebe "implemente a mudança pedida" e não sabe o que fazer."""
    if _is_page_request(objective):
        return page_plan(objective), "page-template"
    plan = GENERIC_TEMPLATE.model_copy(deep=True)
    order = " ".join((objective or "").strip().split())
    for spec in plan.subtasks:
        if spec.title == "Aplicar alterações" and order:
            spec.objective = f"Implementar a mudança pedida no objetivo pai: {order}"
    return plan, "generic-template"


def direct_answer_plan(objective: str) -> DecompositionResult | None:
    """Pergunta curta, sem pedido de alteração, responde direto em vez de editar arquivos."""
    text = " ".join((objective or "").strip().split())
    if not text or len(text) > 280 or _CHANGE_REQUEST.search(text):
        return None
    if "?" not in text and _QUESTION.match(text) is None:
        return None
    return DecompositionResult(
        subtasks=[
            SubTaskSpec(
                title="Responder",
                objective=text,
                metadata={"final_answer": True, "model_operation": True},
            )
        ]
    )


async def resolve_decomposition_plan(
    *,
    settings: Settings,
    run_config: dict[str, Any],
    objective: str,
    project_root: str,
    provider: LLMProvider | None = None,
    requirements: list[dict[str, Any]] | None = None,
) -> tuple[DecompositionResult | None, str]:
    """Ordem: builtin e2e → modelo do provedor escolhido → template genérico → mock (se permitido)."""
    if builtin := builtin_plan_for_objective(objective):
        return builtin, "builtin-e2e"
    if direct := direct_answer_plan(objective):
        return direct, "direct-answer"

    from agent.orchestrator.closing import ensure_closing_stages

    provider_name = str(run_config.get("provider") or settings.default_provider)
    profile = profile_from_run_config(run_config, settings, provider=provider)
    model_plan_error = ""
    if provider_name != "mock":
        model = provider
        if model is None:
            model = build_provider_by_name(provider_name, settings)
        if model is not None:
            digest = guide_digest(project_root, objective)
            language = str(run_config.get("locale") or detect_language(objective))
            try:
                plan = await plan_with_model(
                    model,
                    profile,
                    objective,
                    f"{project_root}\n\n{digest}",
                    language=language,
                    browser_mode=str(run_config.get("browser_mode") or "off"),
                    requirements=requirements,
                    project_root=project_root,
                )
                if plan:
                    return ensure_closing_stages(align_verification(objective, plan)), provider_name
                model_plan_error = "o modelo não devolveu um plano"
            except Exception as exc:
                # A falha do plano do modelo é informação, não ruído: fica na origem do plano
                # para o diagnóstico mostrar por que o template genérico foi usado.
                model_plan_error = f"{type(exc).__name__}: {exc}"

    if run_config.get("use_generic_template", settings.use_generic_decomposition_template):
        plan, source = fallback_plan(objective)
        if model_plan_error:
            source = f"{source} (plano do modelo indisponível: {model_plan_error[:160]})"
        return ensure_closing_stages(align_verification(objective, plan)), source

    if run_config.get("provider") == "mock" or settings.allow_mock_fallback:
        if "e2e" in objective.lower():
            base, source = BUILTIN_E2E_PLAN.model_copy(deep=True), "mock-fallback"
        else:
            base, source = fallback_plan(objective)
            source = "mock-fallback"
        return ensure_closing_stages(align_verification(objective, base)), source

    return None, "none"


def profile_from_run_config(
    run_config: dict[str, Any], settings: Settings, provider: LLMProvider | None = None
) -> ModelProfile:
    model_id = str(
        run_config.get("model_id")
        or getattr(provider, "default_model", None)
        or settings.default_model_id
    )
    low = model_id.lower()
    vision = any(token in low for token in ("-vl", "vl:", "vision", "llava", "moondream"))
    generation = dict(run_config.get("generation") or {})
    generation.setdefault("think", False)
    return ModelProfile(
        model_id=model_id,
        context_limit=int(run_config.get("context_limit", settings.default_context_limit)),
        input_budget=int(run_config.get("input_budget", settings.default_input_budget)),
        output_reserve=int(run_config.get("output_reserve", settings.default_output_reserve)),
        supports_vision=vision,
        generation=generation,
    )


def executable_leaf(metadata: dict | None) -> bool:
    """Ferramenta, verificação ou alteração do modelo já é o passo. Não divide de novo se for atômico."""
    meta = metadata or {}
    if meta.get("atomize") or meta.get("decompose"):
        return False
    return bool(
        meta.get("tool")
        or meta.get("verification")
        or meta.get("model_operation")
        or meta.get("atomic")
        or meta.get("final_answer")
    )


def seal_repeated_steps(parent_title: str, plan: DecompositionResult) -> DecompositionResult:
    """Um filho com o mesmo título do pai vira alteração, em vez de outro plano igual."""
    parent = (parent_title or "").strip().casefold()
    if not parent:
        return plan
    subtasks: list[SubTaskSpec] = []
    changed = False
    for spec in plan.subtasks:
        meta = dict(spec.metadata or {})
        same = spec.title.strip().casefold() == parent
        open_step = not meta.get("tool") and not meta.get("verification") and not meta.get("final_answer")
        if same and open_step:
            meta["model_operation"] = True
            meta["atomic"] = True
            spec = spec.model_copy(update={"metadata": meta})
            changed = True
        subtasks.append(spec)
    if not changed:
        return plan
    return DecompositionResult(subtasks=subtasks)


def plan_copies_siblings(sibling_titles: list[str], plan_titles: list[str], current_title: str) -> bool:
    """O plano novo é a mesma lista de títulos que já existe em volta desta etapa."""

    def norm(items: list[str]) -> list[str]:
        return sorted(item.strip().casefold() for item in items if item and item.strip())

    siblings = norm(sibling_titles)
    planned = norm(plan_titles)
    current = (current_title or "").strip().casefold()
    return len(planned) >= 2 and current in planned and planned == siblings


def apply_decomposition(
    session: Session,
    project_id: uuid.UUID,
    parent_id: uuid.UUID,
    plan: DecompositionResult,
) -> list[uuid.UUID]:
    ts = TaskService(session)
    parent = ts.get_task(parent_id)
    plan = seal_repeated_steps(parent.title, plan)
    if parent.status == TaskStatus.PENDING.value:
        ts.update_status(parent_id, TaskStatusUpdate(status=TaskStatus.PLANNING))

    created_ids: list[uuid.UUID] = []
    for spec in plan.subtasks:
        task = ts.create_task(
            project_id,
            TaskCreate(
                title=spec.title,
                objective=spec.objective,
                scope=spec.scope,
                acceptance_criteria=spec.acceptance_criteria,
                kind=spec.kind,
                parent_id=parent_id,
                metadata=spec.metadata,
            ),
        )
        created_ids.append(task.id)
        # Cada subtarefa ganha um agente lógico: é ele que guarda as descobertas e que
        # responde a consultas quando o pai precisa de detalhe.
        AgentService(session).ensure_agent(task.id)

    for idx, spec in enumerate(plan.subtasks):
        for dep_idx in spec.depends_on_indices:
            # Dependência inválida (fora do plano ou de si mesma) é ignorada: o plano
            # nunca pode criar auto-ciclo nem quebrar a criação das subtarefas.
            if not (0 <= dep_idx < len(created_ids)) or dep_idx == idx:
                continue
            try:
                ts.add_dependency(
                    created_ids[idx],
                    TaskDependencyCreate(depends_on_task_id=created_ids[dep_idx]),
                )
            except DependencyError:
                continue

    return created_ids


def builtin_plan_for_objective(objective: str) -> DecompositionResult | None:
    text = objective.lower()
    # "calculadora" contém "calc"; só o demo explícito usa o plano do fixture.
    if "e2e" in text or "calc.py" in text:
        return BUILTIN_E2E_PLAN
    return None
