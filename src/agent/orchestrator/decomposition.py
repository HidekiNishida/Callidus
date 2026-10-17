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
from agent.providers.llamacpp import LlamaCppProvider
from agent.providers.ollama import OllamaProvider
from agent.services.task_service import TaskService
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
) -> DecompositionResult | None:
    browser_line = (
        "O navegador está ligado. Use browser para pesquisa, checagem, demonstração ou teste. "
        "action: search, navigate, snapshot, click, type, press, scroll ou close."
        if browser_mode in {"headless", "visible"}
        else "O navegador está desligado. Não use a ferramenta browser."
    )
    prompt = (
        f"{language_instruction(language)}\n{browser_line}\n"
        f"Objetivo: {objective}\n\nContexto do projeto:\n{context_snippet}\n\n"
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
    resp = await provider.chat(
        ChatCompletionRequest(messages=budget.messages, profile=profile)
    )
    data, err = parse_json_object(resp.content)
    if err or not data:
        return None
    try:
        plan = DecompositionResult.model_validate(data)
        return plan if plan.subtasks else None
    except Exception:
        return None


_CHANGE_REQUEST = re.compile(
    r"\b(arquiv|código|codigo|implement|cri[ae]|corrig|bug|teste|refactor|fun[cç]|classe|pasta|diret[oó]ri|edite|script|módulo|modulo)\b",
    re.IGNORECASE,
)
_QUESTION = re.compile(
    r"^(que|qual|quais|quando|onde|quem|como|por que|porque|me diga|me fala|what|when|where|who|how)\b",
    re.IGNORECASE,
)


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
) -> tuple[DecompositionResult | None, str]:
    """Ordem: builtin e2e → Ollama (padrão) → template genérico → mock (se permitido)."""
    if builtin := builtin_plan_for_objective(objective):
        return builtin, "builtin-e2e"
    if direct := direct_answer_plan(objective):
        return direct, "direct-answer"

    from agent.orchestrator.closing import ensure_closing_stages

    profile = profile_from_run_config(run_config, settings)
    provider_name = run_config.get("provider") or settings.default_provider
    if provider_name in {"ollama", "llamacpp"}:
        if provider is not None:
            model = provider
        elif provider_name == "llamacpp":
            model = LlamaCppProvider(settings.llamacpp_base_url)
        else:
            model = OllamaProvider(settings.ollama_base_url)
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
            )
            if plan:
                return ensure_closing_stages(plan), provider_name
        except Exception:
            pass

    if run_config.get("use_generic_template", settings.use_generic_decomposition_template):
        return ensure_closing_stages(GENERIC_TEMPLATE.model_copy(deep=True)), "generic-template"

    if run_config.get("provider") == "mock" or settings.allow_mock_fallback:
        base = BUILTIN_E2E_PLAN if "e2e" in objective.lower() else GENERIC_TEMPLATE
        return ensure_closing_stages(base.model_copy(deep=True)), "mock-fallback"

    return None, "none"


def profile_from_run_config(run_config: dict[str, Any], settings: Settings) -> ModelProfile:
    model_id = str(run_config.get("model_id") or settings.default_model_id)
    low = model_id.lower()
    vision = any(token in low for token in ("-vl", "vl:", "vision", "llava", "moondream"))
    return ModelProfile(
        model_id=model_id,
        context_limit=int(run_config.get("context_limit", settings.default_context_limit)),
        input_budget=int(run_config.get("input_budget", settings.default_input_budget)),
        output_reserve=int(run_config.get("output_reserve", settings.default_output_reserve)),
        supports_vision=vision,
    )


def executable_leaf(metadata: dict | None) -> bool:
    """Ferramenta, verificação ou alteração do modelo já é o passo. Não divide de novo."""
    meta = metadata or {}
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

    for idx, spec in enumerate(plan.subtasks):
        for dep_idx in spec.depends_on_indices:
            if 0 <= dep_idx < len(created_ids):
                ts.add_dependency(
                    created_ids[idx],
                    TaskDependencyCreate(depends_on_task_id=created_ids[dep_idx]),
                )

    return created_ids


def builtin_plan_for_objective(objective: str) -> DecompositionResult | None:
    text = objective.lower()
    # "calculadora" contém "calc"; só o demo explícito usa o plano do fixture.
    if "e2e" in text or "calc.py" in text:
        return BUILTIN_E2E_PLAN
    return None
