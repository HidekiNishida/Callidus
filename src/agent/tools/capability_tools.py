"""
Arquivo: src/agent/tools/capability_tools.py
Nome: capability_tools.py
Propósito: capacidades compostas determinísticas que combinam operações do projeto em um
resultado compacto e estruturado.
Responsabilidade: camada de aplicação — ferramentas de alto nível que o modelo chama para
realizar trabalho que seria repetitivo ou frágil de fazer peça por peça (inspecionar subsistema,
rastrear dependência, analisar impacto, encontrar testes relacionados, preparar edição,
validar alteração, revisar diff, diagnosticar falha, recuperar operação).
Componentes: inspect_subsystem, trace_dependency, analyze_impact, find_related_tests,
prepare_edit, validate_change, review_diff, diagnose_failure, recover_operation,
EditPreparation, EditConflict.
Dependências: agent.memory.inspection, agent.memory.layers, agent.memory.state,
agent.memory.operational, agent.orchestrator.task_compiler, agent.orchestrator.task_ir,
agent.persistence.models, agent.security.paths, agent.tools.registry, agent.tools.diffing,
agent.tools.edit_repair, pathlib, re, uuid.
Observações: não criam novas tabelas; leem/gravam via `TaskContext.session`, `TaskStateService`,
`InspectionIndex` e `MemoryLayers`. As operações de edição guardam o hash do arquivo antes da
alteração para detetar conflito quando o arquivo mudar entre a inspeção e a aplicação.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.engineering.dependency_graph import DependencyGraph
from agent.knowledge.graph_service import KnowledgeGraphService
from agent.memory.state import TaskStateService
from agent.persistence.models import ProjectModel, TaskModel
from agent.security.paths import PathSecurityError, resolve_under_root
from agent.tools.edit_repair import python_ok
from agent.tools.registry import ToolContext, ToolSpec

_CTX_NO_SESSION = "contexto da ferramenta sem sessão"

#: Ferramentas de inspeção que toda capacidade composta pode usar.
_INSPECTION_TOOLS = ["list_dir", "glob_files", "search_grep", "read_file"]

#: Limite de caracteres para trechos de arquivo em resultados compactos.
_FILE_SNIPPET_CHARS = 800


@dataclass
class EditPreparation:
    """Resultado de `prepare_edit`: o que o modelo precisa para editar com segurança.

    Atributos:
        path: caminho relativo ao projeto.
        hash: SHA-256 do conteúdo atual (para detetar conflito).
        size: tamanho em bytes.
        lines: quantidade de linhas.
        content: conteúdo completo do arquivo.
        snippets: trechos relevantes para o objetivo da edição.
        conflicts: conflitos conhecidos (vazio quando o arquivo está estável).
        ready: `True` quando a edição pode prosseguir.
    """

    path: str
    hash: str
    size: int
    lines: int
    content: str
    snippets: list[str]
    conflicts: list[str]
    ready: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "hash": self.hash,
            "size": self.size,
            "lines": self.lines,
            "content": self.content,
            "snippets": self.snippets,
            "conflicts": self.conflicts,
            "ready": self.ready,
        }


@dataclass
class EditConflict:
    """Conflito de edição: o arquivo mudou desde a inspeção.

    Atributos:
        path: caminho do arquivo.
        expected_hash: hash que se esperava (da inspeção anterior).
        actual_hash: hash atual no disco.
        message: descrição legível do conflito.
    """

    path: str
    expected_hash: str
    actual_hash: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "expected_hash": self.expected_hash,
            "actual_hash": self.actual_hash,
            "message": self.message,
        }


def _sha256_file(path: Path) -> str:
    import hashlib

    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _file_snippets(content: str, objective: str, limit: int = 3) -> list[str]:
    if not content or not objective:
        return []
    words = {w.lower() for w in re.findall(r"\w{4,}", objective)}
    snippets: list[str] = []
    for line in content.splitlines():
        low = line.lower()
        if any(w in low for w in words):
            snippets.append(line.strip()[:120])
            if len(snippets) >= limit:
                break
    return snippets


def _project_from_context(ctx: ToolContext) -> tuple[ProjectModel, str]:
    """Obtém o modelo do projeto e a raiz a partir do contexto da ferramenta."""
    from agent.persistence.models import ProjectModel as PM

    root = ctx.project_root or "."
    session = ctx.session
    if session is None:
        raise RuntimeError(_CTX_NO_SESSION)
    # Tenta recuperar o projeto pelo root_path.
    from sqlalchemy import select

    row = session.scalar(select(PM).where(PM.root_path == root))
    if row is None:
        # Cria um registro mínimo se ainda não existir.
        row = PM(root_path=root, name=Path(root).name or "projeto")
        session.add(row)
        session.flush()
    return row, root


# -- capacidades compostas -----------------------------------------------------


def inspect_subsystem(ctx: ToolContext, args: dict) -> dict[str, Any]:
    """Inspeciona um subsistema: arquivos, símbolos, dependências e testes relacionados.

    Combina busca no grafo de conhecimento, lista de diretórios e leitura de arquivos
    num único resultado compacto.

    Args:
        ctx: contexto da ferramenta (sessão, projeto, tarefa).
        args: {subsystem: caminho ou nome, objective: objetivo da inspeção, limit: max arquivos}.

    Returns:
        Dicionário com arquivos, símbolos, dependências, testes e resumo do subsistema.
    """
    subsystem = str(args.get("subsystem", ""))
    objective = str(args.get("objective", subsystem))
    limit = int(args.get("limit", 10))
    project, root = _project_from_context(ctx)
    session = ctx.session

    kg = KnowledgeGraphService(session)
    related: list[dict[str, Any]] = []
    try:
        kg.reindex(project.id, root)
        hits = kg.search(project.id, objective or subsystem, limit=limit)
        related = hits
    except Exception:
        pass

    files: list[dict[str, Any]] = []
    for hit in related[:limit]:
        path = hit.get("ref") or hit.get("path", "")
        if not path:
            continue
        try:
            full = resolve_under_root(root, path)
            if full.is_file():
                content = full.read_text(encoding="utf-8", errors="replace")[:_FILE_SNIPPET_CHARS]
                files.append(
                    {
                        "path": path,
                        "kind": hit.get("kind", "file"),
                        "description": hit.get("description", ""),
                        "snippet": content,
                    }
                )
        except (PathSecurityError, OSError):
            continue

    dep_graph = DependencyGraph(root)
    affected = []
    for f in files[:5]:
        try:
            node = dep_graph.get_file_node_id(f["path"])
            if node:
                affected.extend(dep_graph.get_dependents(node))
        except Exception:
            pass

    return {
        "subsystem": subsystem,
        "objective": objective,
        "files": files,
        "affected_components": sorted(set(affected))[:limit],
        "symbols": [h.get("ref", "") for h in related if h.get("ref")][:limit],
        "tests": [h.get("ref", "") for h in related if "test" in str(h.get("ref", "")).lower()][:limit],
        "summary": f"{len(files)} arquivo(s) relacionado(s) a «{subsystem}»",
    }


def trace_dependency(ctx: ToolContext, args: dict) -> dict[str, Any]:
    """Rastreia dependências de um arquivo ou símbolo no grafo do projeto.

    Args:
        ctx: contexto da ferramenta.
        args: {path: caminho do arquivo, direction: 'dependents'|'dependencies', max_depth: int}.

    Returns:
        Nós alcançados, arestas e nível de impacto.
    """
    path = str(args.get("path", ""))
    direction = str(args.get("direction", "dependents"))
    max_depth = int(args.get("max_depth", 3))
    _, root = _project_from_context(ctx)

    dep_graph = DependencyGraph(root)
    try:
        node = dep_graph.get_file_node_id(path)
        if not node:
            return {"path": path, "direction": direction, "nodes": [], "edges": [], "impact": "não encontrado"}
        if direction == "dependencies":
            nodes = dep_graph.get_dependencies(node, max_depth=max_depth)
        else:
            nodes = dep_graph.get_dependents(node, max_depth=max_depth)
    except Exception:
        nodes = []

    return {
        "path": path,
        "direction": direction,
        "max_depth": max_depth,
        "nodes": sorted(nodes),
        "edges": len(nodes),
        "impact": "alto" if len(nodes) > 10 else "medio" if len(nodes) > 3 else "baixo",
    }


def analyze_impact(ctx: ToolContext, args: dict) -> dict[str, Any]:
    """Analisa o impacto de uma alteração: componentes afetados, testes relacionados, risco.

    Combina rastreamento de dependências, busca de testes e complexidade estimada.

    Args:
        ctx: contexto da ferramenta.
        args: {path: caminho alterado, objective: objetivo da mudança}.

    Returns:
        Componentes afetados, testes relacionados, pontuação de risco e sugestões.
    """
    path = str(args.get("path", ""))
    objective = str(args.get("objective", ""))
    project, root = _project_from_context(ctx)
    session = ctx.session

    dep_graph = DependencyGraph(root)
    affected: list[str] = []
    try:
        node = dep_graph.get_file_node_id(path)
        if node:
            affected = dep_graph.get_dependents(node, max_depth=3)
    except Exception:
        pass

    kg = KnowledgeGraphService(session)
    tests: list[str] = []
    try:
        kg.reindex(project.id, root)
        hits = kg.search(project.id, objective or path, limit=10)
        tests = [h.get("ref", "") for h in hits if "test" in str(h.get("ref", "")).lower()]
    except Exception:
        pass

    risk_score = min(100, len(affected) * 8 + len(tests) * 4)
    risk = "alto" if risk_score >= 60 else "medio" if risk_score >= 30 else "baixo"

    return {
        "path": path,
        "objective": objective,
        "affected_components": sorted(affected)[:20],
        "related_tests": sorted(tests)[:10],
        "risk_score": risk_score,
        "risk": risk,
        "suggestions": [
            "Executar testes relacionados antes e depois da alteração",
            "Revisar componentes afetados para evitar regressões",
        ],
    }


def find_related_tests(ctx: ToolContext, args: dict) -> dict[str, Any]:
    """Encontra testes relacionados a um arquivo ou objetivo.

    Args:
        ctx: contexto da ferramenta.
        args: {path: caminho do arquivo, objective: objetivo, limit: int}.

    Returns:
        Lista de arquivos de teste e verificadores sugeridos.
    """
    path = str(args.get("path", ""))
    objective = str(args.get("objective", ""))
    limit = int(args.get("limit", 10))
    project, root = _project_from_context(ctx)
    session = ctx.session

    tests: list[str] = []
    try:
        from pathlib import Path as _P

        # Busca direta por arquivos de teste que mencionam o caminho ou o objetivo.
        query = objective or path
        kg = KnowledgeGraphService(session)
        kg.reindex(project.id, root)
        hits = kg.search(project.id, query, limit=limit * 2)
        for h in hits:
            ref = str(h.get("ref", ""))
            if "test" in ref.lower():
                tests.append(ref)
                if len(tests) >= limit:
                    break
    except Exception:
        pass

    # Fallback: procura arquivos de teste na raiz.
    if not tests:
        try:
            root_p = _P(root)
            for pat in ("test_*.py", "*_test.py", "tests/**/*.py"):
                for f in root_p.glob(pat):
                    rel = f.relative_to(root).as_posix()
                    if objective and objective.lower() in rel.lower():
                        tests.append(rel)
                    if len(tests) >= limit:
                        break
        except Exception:
            pass

    return {
        "path": path,
        "objective": objective,
        "tests": sorted(tests)[:limit],
        "suggested_verifier": "pytest" if tests else None,
    }


def prepare_edit(ctx: ToolContext, args: dict) -> dict[str, Any]:
    """Prepara uma edição: lê o arquivo, guarda o hash e deteta conflitos.

    O hash é gravado nos metadados da tarefa para que `validate_change` possa
    verificar se o arquivo não mudou entre a preparação e a aplicação.

    Args:
        ctx: contexto da ferramenta.
        args: {path: caminho do arquivo, objective: objetivo da edição}.

    Returns:
        `EditPreparation` com conteúdo, hash, trechos e sinal de prontidão.
    """
    path = str(args.get("path", ""))
    objective = str(args.get("objective", ""))
    _, root = _project_from_context(ctx)
    session = ctx.session

    try:
        full = resolve_under_root(root, path)
    except PathSecurityError as exc:
        return {"path": path, "ready": False, "conflicts": [str(exc)], "error": "caminho fora do escopo"}

    if not full.is_file():
        return {"path": path, "ready": False, "conflicts": ["arquivo não encontrado"], "error": "não encontrado"}

    try:
        content = full.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"path": path, "ready": False, "conflicts": [str(exc)], "error": "leitura falhou"}

    file_hash = _sha256_file(full)
    snippets = _file_snippets(content, objective)

    # Grava o hash nos metadados da tarefa para detetar conflito depois.
    if ctx.task_id:
        task = session.get(TaskModel, ctx.task_id)
        if task is not None:
            meta = dict(task.metadata_json or {})
            pending_edits = meta.get("pending_edits", {})
            pending_edits[path] = {
                "hash": file_hash,
                "size": full.stat().st_size,
                "objective": objective,
            }
            meta["pending_edits"] = pending_edits
            task.metadata_json = meta
            session.flush()

    return EditPreparation(
        path=path,
        hash=file_hash,
        size=full.stat().st_size,
        lines=content.count("\n") + 1,
        content=content,
        snippets=snippets,
        conflicts=[],
        ready=True,
    ).to_dict()


def validate_change(ctx: ToolContext, args: dict) -> dict[str, Any]:
    """Valida uma alteração: sintaxe do Python, arquivo não conflitado, testes relacionados.

    Args:
        ctx: contexto da ferramenta.
        args: {path: caminho alterado, content: conteúdo novo (opcional), expected_hash: hash esperado}.

    Returns:
        Resultado da validação: válido, conflitos, erros de sintaxe, testes sugeridos.
    """
    path = str(args.get("path", ""))
    new_content = args.get("content")
    expected_hash = args.get("expected_hash")
    _, root = _project_from_context(ctx)

    conflicts: list[str] = []
    errors: list[str] = []

    # Deteta conflito: o arquivo mudou desde a preparação.
    if expected_hash:
        try:
            full = resolve_under_root(root, path)
            actual_hash = _sha256_file(full)
            if actual_hash != expected_hash:
                conflicts.append(
                    f"o arquivo mudou desde a preparação (esperado {expected_hash[:12]}, atual {actual_hash[:12]})"
                )
        except (PathSecurityError, OSError):
            conflicts.append("não foi possível verificar o arquivo no disco")

    # Valida sintaxe se for Python e o conteúdo foi fornecido.
    if new_content is not None and path.endswith(".py"):
        ok = python_ok(new_content)
        if not ok:
            errors.append("erro de sintaxe")

    # Sugere testes relacionados.
    tests: list[str] = []
    try:
        from pathlib import Path as _P

        root_p = _P(root)
        for f in root_p.glob("tests/**/*.py"):
            rel = f.relative_to(root).as_posix()
            if path.replace(".py", "").split("/")[-1] in rel:
                tests.append(rel)
    except Exception:
        pass

    return {
        "path": path,
        "valid": not conflicts and not errors,
        "conflicts": conflicts,
        "errors": errors,
        "suggested_tests": sorted(tests)[:5],
        "verifier": "pytest" if tests else None,
    }


def review_diff(_ctx: ToolContext, args: dict) -> dict[str, Any]:
    """Revisa um diff: resumo de alterações, arquivos afetados, riscos.

    Args:
        ctx: contexto da ferramenta.
        args: {diff: texto do diff, path: caminho do arquivo (opcional)}.

    Returns:
        Resumo da revisão com estatísticas e riscos.
    """
    diff_text = str(args.get("diff", ""))
    path = str(args.get("path", ""))

    added = diff_text.count("\n+") - diff_text.count("\n+++")
    removed = diff_text.count("\n-") - diff_text.count("\n---")
    files_affected = len(set(re.findall(r"^\+\+\+ b/(.+)$", diff_text, re.MULTILINE)))

    risk = "baixo"
    if added + removed > 100:
        risk = "alto"
    elif added + removed > 30:
        risk = "medio"

    return {
        "path": path,
        "files_affected": files_affected,
        "lines_added": max(0, added),
        "lines_removed": max(0, removed),
        "risk": risk,
        "summary": f"{files_affected} arquivo(s), +{max(0, added)}/-{max(0, removed)} linha(s)",
    }


def diagnose_failure(_ctx: ToolContext, args: dict) -> dict[str, Any]:
    """Diagnostica uma falha: classifica a causa e sugere uma estratégia de recuperação.

    Args:
        ctx: contexto da ferramenta.
        args: {error: mensagem de erro, task_id: identificador da tarefa, context: contexto adicional}.

    Returns:
        Categoria da falha, causa provável, estratégia sugerida e se é recuperável.
    """
    error = str(args.get("error", ""))
    task_id = args.get("task_id")
    context = str(args.get("context", ""))

    text = f"{error} {context}".lower()
    category = "desconhecido"
    strategy = "revisar o erro e tentar novamente com mais contexto"
    recoverable = True

    if any(w in text for w in ("syntax error", "syntaxerror", "indentation", "nameerror", "typeerror")):
        category = "erro de código"
        strategy = "corrigir a sintaxe ou o nome e reexecutar a etapa de implementação"
    elif any(w in text for w in ("import", "modulenotfound", "no module")):
        category = "erro de importação"
        strategy = "instalar a dependência ausente ou corrigir o caminho do import"
    elif any(w in text for w in ("timeout", "timed out")):
        category = "timeout"
        strategy = "retry com maior orçamento de tempo ou dividir a operação"
    elif any(w in text for w in ("permission", "permissão", "access denied")):
        category = "permissão"
        strategy = "verificar permissões do arquivo ou do diretório"
    elif any(w in text for w in ("conflict", "conflito", "stale")):
        category = "conflito de edição"
        strategy = "reinspecionar o arquivo e reaplicar a alteração sobre a versão atual"
    elif any(w in text for w in ("test failed", "assertion", "falha no teste")):
        category = "falha de teste"
        strategy = "corrigir a implementação para satisfazer o teste falho"
    elif any(w in text for w in ("provider", "modelo", "ollama", "conexão")):
        category = "erro de provider"
        strategy = "verificar o provedor de modelo ou escalonar para um modelo mais capaz"
    else:
        category = "erro de execução"
        strategy = "reinspecionar evidências e tentar uma abordagem alternativa"

    return {
        "error": error[:500],
        "category": category,
        "cause": error[:200],
        "strategy": strategy,
        "recoverable": recoverable,
        "task_id": task_id,
    }


def recover_operation(ctx: ToolContext, args: dict) -> dict[str, Any]:
    """Recupera uma operação falhada: restaura estado conhecido ou sugere alternativa.

    Args:
        ctx: contexto da ferramenta.
        args: {task_id: identificador da tarefa, operation: id da operação, strategy: estratégia}.

    Returns:
        Resultado da recuperação: restaurado, alternativa sugerida ou bloqueado.
    """
    task_id = args.get("task_id")
    operation = str(args.get("operation", ""))
    strategy = str(args.get("strategy", ""))
    _, _ = _project_from_context(ctx)
    session = ctx.session

    # Tenta restaurar o estado da tarefa via TaskStateService.
    state_service = TaskStateService(session)
    if task_id:
        try:
            state = state_service.get_task_state(uuid.UUID(str(task_id)) if isinstance(task_id, str) else task_id)
            if state:
                return {
                    "task_id": str(task_id),
                    "operation": operation,
                    "recovered": True,
                    "strategy": "estado restaurado do banco",
                    "state": {
                        "status": state.status,
                        "objective": state.objective,
                        "pending": state.pending,
                        "last_error": state.last_error,
                    },
                }
        except (ValueError, AttributeError):
            pass

    return {
        "task_id": str(task_id) if task_id else None,
        "operation": operation,
        "recovered": False,
        "strategy": strategy or "sem estratégia informada",
        "alternative": "reinspecionar o projeto e replanejar a operação",
    }


# -- registro opcional como ferramentas ---------------------------------------


def register_capability_tools(registry: Any) -> None:
    """Registra as capacidades compostas no registro de ferramentas (opcional).

    Cada capacidade fica disponível para o modelo chamar como uma ferramenta
    com entrada validada e saída estruturada.
    """
    specs = [
        ToolSpec(
            id="inspect_subsystem",
            name="Inspecionar subsistema",
            description="Lê arquivos, símbolos, dependências e testes de um subsistema.",
            input_schema={
                "type": "object",
                "properties": {
                    "subsystem": {"type": "string"},
                    "objective": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["subsystem"],
            },
        ),
        ToolSpec(
            id="trace_dependency",
            name="Rastrear dependência",
            description="Rastreia dependências ou dependentes de um arquivo no grafo do projeto.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "direction": {"type": "string", "enum": ["dependents", "dependencies"]},
                    "max_depth": {"type": "integer"},
                },
                "required": ["path"],
            },
        ),
        ToolSpec(
            id="analyze_impact",
            name="Analisar impacto",
            description="Analisa componentes afetados, testes relacionados e risco de uma alteração.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "objective": {"type": "string"},
                },
                "required": ["path"],
            },
        ),
        ToolSpec(
            id="find_related_tests",
            name="Encontrar testes relacionados",
            description="Localiza arquivos de teste relacionados a um arquivo ou objetivo.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "objective": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": [],
            },
        ),
        ToolSpec(
            id="prepare_edit",
            name="Preparar edição",
            description="Lê um arquivo, guarda seu hash e deteta conflitos antes de editar.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}, "objective": {"type": "string"}},
                "required": ["path"],
            },
        ),
        ToolSpec(
            id="validate_change",
            name="Validar alteração",
            description="Valida sintaxe, deteta conflitos e sugere testes para uma alteração.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "expected_hash": {"type": "string"},
                },
                "required": ["path"],
            },
        ),
        ToolSpec(
            id="review_diff",
            name="Revisar diff",
            description="Resuma alterações, arquivos afetados e nível de risco de um diff.",
            input_schema={
                "type": "object",
                "properties": {"diff": {"type": "string"}, "path": {"type": "string"}},
                "required": ["diff"],
            },
        ),
        ToolSpec(
            id="diagnose_failure",
            name="Diagnosticar falha",
            description="Classifica a causa de uma falha e sugere uma estratégia de recuperação.",
            input_schema={
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                    "task_id": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["error"],
            },
        ),
        ToolSpec(
            id="recover_operation",
            name="Recuperar operação",
            description="Restaura o estado conhecido de uma tarefa ou sugere alternativa.",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "operation": {"type": "string"},
                    "strategy": {"type": "string"},
                },
                "required": [],
            },
        ),
    ]

    from contextlib import suppress

    for spec in specs:
        with suppress(Exception):
            registry.register(spec)
