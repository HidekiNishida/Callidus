# src/agent/guides/discover.py — guias que os agentes de código leem no repositório
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROOT_FILES: tuple[tuple[str, str], ...] = (
    ("AGENTS.override.md", "agents"),
    ("AGENTS.md", "agents"),
    ("CLAUDE.md", "claude"),
    (".claude/CLAUDE.md", "claude"),
    ("CLAUDE.local.md", "claude"),
    ("GEMINI.md", "gemini"),
    (".github/copilot-instructions.md", "copilot"),
    (".cursorrules", "cursor"),
    ("llms.txt", "llms"),
    ("docs/project-context.md", "docs"),
    ("docs/README.md", "docs"),
)

PER_FILE = 2500
TOTAL = 12000
SKIP = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist"}


@dataclass
class GuideHit:
    kind: str
    path: str
    text: str


def reply_capabilities(model_id: str) -> dict[str, bool]:
    """Formatos de resposta que o chat consegue mostrar. Visão depende do modelo."""
    low = model_id.lower()
    vision = any(token in low for token in ("-vl", "vl:", "vision", "llava", "moondream"))
    return {
        "markdown": True,
        "headings": True,
        "lists": True,
        "tables": True,
        "code": True,
        "mermaid": True,
        "sources": True,
        "vision": vision,
    }


def capability_line(model_id: str) -> str:
    caps = reply_capabilities(model_id)
    names = [name for name, ok in caps.items() if ok and name != "vision"]
    vision = "pode ver imagens anexadas" if caps["vision"] else "não vê imagem; use o caminho do arquivo"
    return f"Formatos deste modelo ({model_id}): {', '.join(names)}. Visão: {vision}."


def discover_guides(project_root: str | Path, objective: str = "") -> list[GuideHit]:
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        return []
    hits: list[GuideHit] = []
    used = 0
    for rel, kind in ROOT_FILES:
        if kind == "readme":
            continue
        hit = _read(root, rel, kind)
        if hit is None:
            continue
        if used + len(hit.text) > TOTAL:
            break
        hits.append(hit)
        used += len(hit.text)
    if not any(hit.kind == "agents" for hit in hits):
        readme = _read(root, "README.md", "readme", limit=1200)
        if readme and used + len(readme.text) <= TOTAL:
            hits.append(readme)
            used += len(readme.text)
    for path in _scoped(root, ".cursor/rules", (".md", ".mdc")):
        hit = _clip(root, path, "cursor-rule")
        if hit and used + len(hit.text) <= TOTAL:
            hits.append(hit)
            used += len(hit.text)
    for path in _scoped(root, ".github/instructions", (".md",)):
        if not path.name.endswith(".instructions.md") and path.suffix != ".md":
            continue
        hit = _clip(root, path, "copilot")
        if hit and used + len(hit.text) <= TOTAL:
            hits.append(hit)
            used += len(hit.text)
    for skill in _skills(root):
        if used + len(skill.text) > TOTAL:
            break
        hits.append(skill)
        used += len(skill.text)
    mentioned = objective.lower()
    if mentioned:
        try:
            children = [p for p in root.iterdir() if p.is_dir() and p.name not in SKIP]
        except OSError:
            children = []
        for child in children[:40]:
            if child.name.lower() not in mentioned:
                continue
            nested = child / "AGENTS.md"
            hit = _clip(root, nested, "agents")
            if hit and used + len(hit.text) <= TOTAL:
                hits.append(hit)
                used += len(hit.text)
    return hits


def guide_digest(project_root: str | Path, objective: str = "") -> str:
    hits = discover_guides(project_root, objective)
    if not hits:
        return "(nenhum AGENTS.md, CLAUDE.md, GEMINI.md, regra de editor ou SKILL.md na raiz)"
    parts = []
    for hit in hits:
        parts.append(f"### {hit.kind}: {hit.path}\n{hit.text}")
    return "\n\n".join(parts)


def _read(root: Path, rel: str, kind: str, limit: int = PER_FILE) -> GuideHit | None:
    return _clip(root, root / rel, kind, limit=limit)


def _clip(root: Path, path: Path, kind: str, limit: int = PER_FILE) -> GuideHit | None:
    try:
        resolved = path.resolve()
    except OSError:
        return None
    if root not in resolved.parents and resolved != root:
        return None
    if not resolved.is_file() or any(part in SKIP for part in resolved.relative_to(root).parts):
        return None
    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if path.suffix == ".mdc" or text.startswith("---"):
        text = _strip_front_matter(text)
    text = text.strip()
    if not text:
        return None
    if len(text) > limit:
        text = text[:limit] + "\n…"
    rel = str(resolved.relative_to(root))
    return GuideHit(kind=kind, path=rel, text=text)


def _strip_front_matter(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + 4 :].strip()


def _scoped(root: Path, folder: str, suffixes: tuple[str, ...]) -> list[Path]:
    base = root / folder
    if not base.is_dir():
        return []
    found: list[Path] = []
    try:
        entries = sorted(base.iterdir(), key=lambda p: p.name)
    except OSError:
        return []
    for path in entries:
        if path.suffix in suffixes and path.is_file():
            found.append(path)
        if len(found) >= 4:
            break
    return found


def _skills(root: Path) -> list[GuideHit]:
    hits: list[GuideHit] = []
    for folder in ("skills", ".agents/skills", ".cursor/skills"):
        base = root / folder
        if not base.is_dir():
            continue
        try:
            entries = sorted(p for p in base.rglob("SKILL.md") if p.is_file())
        except OSError:
            continue
        for path in entries[:8]:
            if any(part in SKIP for part in path.relative_to(root).parts):
                continue
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")[:2000]
            except OSError:
                continue
            name, description = _skill_meta(raw, path.parent.name)
            rel = str(path.relative_to(root))
            hits.append(GuideHit(kind="skill", path=rel, text=f"{name}: {description}"))
            if len(hits) >= 8:
                return hits
    return hits


def _skill_meta(raw: str, fallback: str) -> tuple[str, str]:
    name = fallback
    description = "fluxo reutilizável"
    block = raw
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        block = raw[3:end] if end != -1 else raw
    found_name = re.search(r"^name:\s*(.+)$", block, re.M)
    found_desc = re.search(r"^description:\s*(.+)$", block, re.M)
    if found_name:
        name = found_name.group(1).strip().strip("\"'")
    if found_desc:
        description = found_desc.group(1).strip().strip("\"'")
    return name, description[:240]
