"""
Arquivo: src/agent/memory/tool_results.py
Nome: tool_results.py
Propósito: processar, armazenar e recuperar resultados de ferramentas fora do contexto do modelo.
Responsabilidade: camada de aplicação — camada intermediária entre ferramentas e contexto do LLM.
Componentes: ToolResultProcessor, ToolResultArtifact, store_result,
retrieve_artifact, search_in_artifact, read_artifact_range.
Dependências: agent.memery.inspection, agent.persistence.models, sqlalchemy, hashlib, pathlib, json.
Observações: resultados grandes viram artefatos com referência; o modelo recebe representação compacta.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from agent.persistence.models import TaskModel

from agent.domain.enums import MemoryKind

_ARTIFACT_DIR = "data/artifacts"
_MAX_INLINE_CHARS = 3000
_MAX_SUMMARY_CHARS = 800
_MAX_SNIPPET_CHARS = 200
_DEFAULT_SNIPPETS = 5


@dataclass
class ToolResultArtifact:
    """Registro de um resultado de ferramenta armazenado como artefato."""

    id: uuid.UUID
    task_id: uuid.UUID
    run_id: uuid.UUID | None
    tool_name: str
    tool_args: dict[str, Any]
    success: bool
    content_type: str
    original_chars: int
    original_lines: int
    summary: str
    snippets: list[str]
    file_path: str | None
    hash: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "task_id": str(self.task_id),
            "run_id": str(self.run_id) if self.run_id else None,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "success": self.success,
            "content_type": self.content_type,
            "original_chars": self.original_chars,
            "original_lines": self.original_lines,
            "summary": self.summary,
            "snippets": self.snippets,
            "file_path": self.file_path,
            "hash": self.hash,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolResultArtifact:
        return cls(
            id=uuid.UUID(data["id"]),
            task_id=uuid.UUID(data["task_id"]),
            run_id=uuid.UUID(data["run_id"]) if data.get("run_id") else None,
            tool_name=data["tool_name"],
            tool_args=data["tool_args"],
            success=data["success"],
            content_type=data["content_type"],
            original_chars=data["original_chars"],
            original_lines=data["original_lines"],
            summary=data["summary"],
            snippets=data["snippets"],
            file_path=data.get("file_path"),
            hash=data["hash"],
            created_at=data["created_at"],
            metadata=data.get("metadata", {}),
        )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _detect_content_type(tool_name: str, content: str, _args: dict[str, Any]) -> str:
    """Detecta o tipo de conteúdo para estratégia de processamento."""
    if tool_name in ("read_file", "write_file", "edit_file"):
        return "file"
    if tool_name in ("search_grep", "glob_files"):
        return "search"
    if tool_name in ("list_dir", "git_status", "git_diff"):
        return "listing"
    if tool_name in ("run_test", "pytest", "test"):
        return "test_output"
    if tool_name in ("bash", "shell", "terminal"):
        return "terminal"
    if "error" in content.lower()[:200] or "traceback" in content.lower()[:200]:
        return "error"
    if content.strip().startswith("{") or content.strip().startswith("["):
        return "json"
    return "text"


def _extract_snippets(content: str, tool_name: str, max_snippets: int = _DEFAULT_SNIPPETS) -> list[str]:
    """Extrai trechos relevantes do conteúdo baseado no tipo de ferramenta."""
    snippets: list[str] = []
    lines = content.splitlines()

    if tool_name in ("read_file", "write_file", "edit_file"):
        # Para arquivos: primeiras linhas, linhas com definições, últimas linhas
        for i, line in enumerate(lines):
            if (
                i < 10
                or i >= len(lines) - 5
                or any(kw in line for kw in ("def ", "class ", "function ", "import ", "from ", "export "))
            ):
                snippets.append(f"L{i + 1}: {line[:_MAX_SNIPPET_CHARS]}")
            if len(snippets) >= max_snippets:
                break

    elif tool_name in ("search_grep", "glob_files"):
        # Para busca: primeiras ocorrências
        for i, line in enumerate(lines[:max_snippets]):
            snippets.append(f"L{i + 1}: {line[:_MAX_SNIPPET_CHARS]}")

    elif tool_name in ("bash", "shell", "terminal", "run_test", "pytest"):
        # Para terminal/testes: erros, falhas, resumo final
        error_lines = [
            line
            for line in lines
            if any(kw in line.lower() for kw in ("error", "fail", "exception", "traceback"))
        ]
        for line in error_lines[:max_snippets]:
            snippets.extend([line[:_MAX_SNIPPET_CHARS]])
        if not snippets and lines:
            snippets.append(lines[-1][:_MAX_SNIPPET_CHARS])

    else:
        # Genérico: primeiras e últimas linhas
        for i, line in enumerate(lines[: max_snippets // 2]):
            snippets.append(f"L{i + 1}: {line[:_MAX_SNIPPET_CHARS]}")
        for i, line in enumerate(lines[-max_snippets // 2 :]):
            snippets.append(f"L{len(lines) - max_snippets // 2 + i + 1}: {line[:_MAX_SNIPPET_CHARS]}")

    return snippets[:max_snippets]


def _generate_summary(content: str, tool_name: str, success: bool, args: dict[str, Any]) -> str:
    """Gera resumo conciso do resultado."""
    if not success:
        return f"{tool_name} falhou: {content[:300]}"

    lines = content.splitlines()
    n_lines = len(lines)
    n_chars = len(content)

    if tool_name in ("read_file", "write_file", "edit_file"):
        path = args.get("path", "?")
        return f"{tool_name} em {path}: {n_lines} linhas, {n_chars} chars"
    elif tool_name == "search_grep":
        pattern = args.get("pattern", "?")
        matches = len([line for line in lines if line.strip()])
        return f"grep '{pattern}': {matches} ocorrências em {n_lines} linhas"
    elif tool_name == "list_dir":
        path = args.get("path", "?")
        return f"list_dir {path}: {n_lines} entradas"
    elif tool_name in ("bash", "shell", "terminal"):
        return f"terminal: {n_lines} linhas de saída, {n_chars} chars"
    elif tool_name in ("run_test", "pytest", "test"):
        return f"testes: {n_lines} linhas, {n_chars} chars"
    elif tool_name in ("git_status", "git_diff"):
        return f"git {tool_name.split('_')[1]}: {n_lines} linhas"
    else:
        return f"{tool_name}: {n_lines} linhas, {n_chars} chars"


class ToolResultProcessor:
    """Processa resultados de ferramentas: armazena completos, devolve compactos."""

    def __init__(self, session: Session, artifacts_root: Path | None = None) -> None:
        self._session = session
        self._artifacts_root = artifacts_root or Path(_ARTIFACT_DIR)
        self._artifacts_root.mkdir(parents=True, exist_ok=True)

    def process(
        self,
        task: TaskModel,
        tool_name: str,
        tool_args: dict[str, Any],
        result: dict[str, Any],
        run_id: uuid.UUID | None = None,
    ) -> tuple[str, ToolResultArtifact]:
        """Processa resultado: armazena completo, retorna representação compacta."""
        content = self._extract_content(result)
        success = bool(result.get("success", False))
        content_type = _detect_content_type(tool_name, content, tool_args)
        original_chars = len(content)
        original_lines = content.count("\n") + 1 if content else 0
        content_hash = _sha256_content(content)

        # Verificar se já existe (idempotência por hash)
        existing = self._find_by_hash(task.id, content_hash)
        if existing:
            return self._compact_representation(existing), existing

        # Extrair snippets e resumo
        snippets = _extract_snippets(content, tool_name)
        summary = _generate_summary(content, tool_name, success, tool_args)

        # Salvar artefato no disco
        artifact_id = uuid.uuid4()
        artifact_file = self._artifacts_root / f"{artifact_id}.json"
        artifact_data = {
            "id": str(artifact_id),
            "task_id": str(task.id),
            "run_id": str(run_id) if run_id else None,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "success": success,
            "content_type": content_type,
            "original_chars": original_chars,
            "original_lines": original_lines,
            "summary": summary,
            "snippets": snippets,
            "file_path": tool_args.get("path"),
            "hash": content_hash,
            "created_at": _now_iso(),
            "metadata": {"result_keys": list(result.keys())},
        }
        artifact_file.write_text(json.dumps(artifact_data, ensure_ascii=False), encoding="utf-8")

        # Registrar na memória operacional como artefato (nível 3)
        from agent.memory.operational import remember_artifact

        remember_artifact(
            self._session,
            task,
            title=f"{tool_name} result",
            ref=f"artifact:{artifact_id}",
            summary=summary,
        )

        artifact = ToolResultArtifact(**artifact_data)
        return self._compact_representation(artifact), artifact

    def _extract_content(self, result: dict[str, Any]) -> str:
        """Extrai o conteúdo textual principal do resultado."""
        if not isinstance(result, dict):
            return str(result)
        for key in ("content", "stdout", "output", "text", "body"):
            if key in result and isinstance(result[key], str):
                return result[key]
        # Fallback: JSON do resultado completo
        return json.dumps(result, ensure_ascii=False, default=str)

    def _find_by_hash(self, task_id: uuid.UUID, content_hash: str) -> ToolResultArtifact | None:
        """Procura artefato existente pelo hash."""
        # Buscar na memória de artefatos da task
        from agent.memory.operational import recall

        artifacts = recall(self._session, project_id=task_id, kind=MemoryKind.ARTIFACT.value, limit=100)
        for art in artifacts:
            outline = art.outline_json or {}
            if outline.get("ref") and outline["ref"].startswith("artifact:"):
                # Verificar arquivo
                artifact_id = outline["ref"].split(":")[1]
                artifact_file = self._artifacts_root / f"{artifact_id}.json"
                if artifact_file.exists():
                    data = json.loads(artifact_file.read_text(encoding="utf-8"))
                    if data.get("hash") == content_hash:
                        return ToolResultArtifact.from_dict(data)
        return None

    def _compact_representation(self, artifact: ToolResultArtifact) -> str:
        """Gera representação compacta para o modelo."""
        lines = [
            f"RESULTADO: {artifact.tool_name}",
            f"STATUS: {'OK' if artifact.success else 'FALHOU'}",
            f"TAMANHO: {artifact.original_chars} chars, {artifact.original_lines} linhas",
            f"RESUMO: {artifact.summary}",
        ]
        if artifact.snippets:
            lines.append("TRECHOS RELEVANTES:")
            for s in artifact.snippets[:3]:
                lines.extend([f"  - {s}"])
            if len(artifact.snippets) > 3:
                lines.append(f"  ... e mais {len(artifact.snippets) - 3} trechos")
        lines.append(f"ARQUIVO ORIGINAL: artifact://{artifact.id}")
        lines.append("CONSULTA DISPONÍVEL:")
        lines.append("  - retrieve_artifact <id>")
        lines.append("  - search_in_artifact <id> <query>")
        lines.append("  - read_artifact_range <id> <start> <end>")
        return "\n".join(lines)

    def retrieve_artifact(self, artifact_id: uuid.UUID) -> ToolResultArtifact | None:
        """Recupera artefato completo pelo ID."""
        artifact_file = self._artifacts_root / f"{artifact_id}.json"
        if not artifact_file.exists():
            return None
        data = json.loads(artifact_file.read_text(encoding="utf-8"))
        return ToolResultArtifact.from_dict(data)

    def search_in_artifact(self, artifact_id: uuid.UUID, query: str, limit: int = 20) -> list[str]:
        """Busca termo dentro do artefato, retorna linhas com contexto."""
        artifact = self.retrieve_artifact(artifact_id)
        if not artifact:
            return []
        # O conteúdo original precisa ser reconstruído ou buscado no arquivo
        # Por simplicidade, buscar nos snippets e summary
        query_lower = query.lower()
        results = [snippet for snippet in artifact.snippets if query_lower in snippet.lower()]
        if query_lower in artifact.summary.lower():
            results.insert(0, f"SUMMARY: {artifact.summary}")
        return results[:limit]

    def read_artifact_range(self, artifact_id: uuid.UUID, start: int, end: int) -> str | None:
        """Lê faixa de linhas do artefato original."""
        # O conteúdo completo não é guardado no artefato JSON (seria duplicação)
        # Para implementar, precisaríamos guardar o conteúdo ou referenciar o arquivo original
        # Por enquanto, retorna None indicando que precisa reler a fonte
        artifact = self.retrieve_artifact(artifact_id)
        if not artifact:
            return None
        if artifact.file_path:
            return f"[Use read_file para ler {artifact.file_path} linhas {start}-{end}]"
        return "[Conteúdo original não armazenado; use retrieve_artifact para ver snippets]"


def store_result(
    session: Session,
    task: TaskModel,
    tool_name: str,
    tool_args: dict[str, Any],
    result: dict[str, Any],
    run_id: uuid.UUID | None = None,
    artifacts_root: Path | None = None,
) -> tuple[str, ToolResultArtifact]:
    """Função de conveniência para processar e armazenar resultado de ferramenta."""
    processor = ToolResultProcessor(session, artifacts_root)
    return processor.process(task, tool_name, tool_args, result, run_id)


def retrieve_artifact(
    session: Session,
    artifact_id: uuid.UUID,
    artifacts_root: Path | None = None,
) -> ToolResultArtifact | None:
    """Recupera artefato completo pelo ID."""
    processor = ToolResultProcessor(session, artifacts_root)
    return processor.retrieve_artifact(artifact_id)


def search_in_artifact(
    session: Session,
    artifact_id: uuid.UUID,
    query: str,
    limit: int = 20,
    artifacts_root: Path | None = None,
) -> list[str]:
    """Busca termo dentro do artefato."""
    processor = ToolResultProcessor(session, artifacts_root)
    return processor.search_in_artifact(artifact_id, query, limit)


def read_artifact_range(
    session: Session,
    artifact_id: uuid.UUID,
    start: int,
    end: int,
    artifacts_root: Path | None = None,
) -> str | None:
    """Lê faixa de linhas do artefato original."""
    processor = ToolResultProcessor(session, artifacts_root)
    return processor.read_artifact_range(artifact_id, start, end)
