# src/agent/skills/catalog/loader.py — Carrega Skills do catálogo em Markdown (fonte de verdade)
#
# O catálogo `skills/` do repositório é a fonte de verdade das competências profissionais:
# cada arquivo `.md` descreve critérios de ativação, proibições, procedimentos, regras de
# validação, riscos, ferramentas autorizadas e palavras-chave. Este módulo converte esses
# arquivos em `SkillSpec`, de modo que a mesma definição sirva para descoberta, seleção
# sob demanda e injeção no prompt.
from __future__ import annotations

import logging
import re
from pathlib import Path

from agent.skills.models import SkillSpec

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

# Seções do markdown → campo do SkillSpec.
_SECTION_FIELDS: dict[str, str] = {
    "procedimentos": "procedures",
    "procedimento": "procedures",
    "passos": "procedures",
    "instruções": "procedures",
    "instructions": "procedures",
    "validação": "validation_rules",
    "validacao": "validation_rules",
    "aceite": "validation_rules",
    "critérios de validação": "validation_rules",
    "riscos": "risk_factors",
    "controle de riscos": "risk_factors",
}

# Seções de texto livre lidas como lista de itens.
_LIST_SECTIONS: dict[str, str] = {
    "critérios de ativação": "activation_criteria",
    "criterios de ativação": "activation_criteria",
    "quando utilizar": "activation_criteria",
    "quando não utilizar": "prohibited_criteria",
    "quando nao utilizar": "prohibited_criteria",
    "situações proibidas": "prohibited_criteria",
    "ferramentas autorizadas": "required_tools",
    "ferramentas permitidas": "required_tools",
    "exemplos": "examples",
}

_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def default_catalog_dir() -> Path | None:
    """Diretório do catálogo shipped com o repositório (`skills/` na raiz do projeto).

    A raiz do repositório é reconhecida pelo `pyproject.toml`; assim o catálogo do agente
    (`src/agent/skills/`) nunca é confundido com o catálogo editável (`skills/`).

    Retorna `None` quando o pacote foi instalado sem o repositório (uso como dependência),
    caso em que o agente rely apenas nas skills embutidas.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if not (parent / "pyproject.toml").is_file():
            continue
        candidate = parent / "skills"
        if candidate.is_dir() and any(candidate.glob("*.md")):
            return candidate
    return None


def catalog_dir(project_root: str | Path | None = None) -> Path | None:
    """Resolve o catálogo a usar: o do projeto, se existir; senão o do repositório."""
    if project_root:
        candidate = Path(project_root).resolve() / "skills"
        if candidate.is_dir():
            return candidate
    return default_catalog_dir()


def _split_list(value: str) -> list[str]:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [item.strip().strip("\"'") for item in value.split(",") if item.strip()]


def parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Separa o frontmatter do corpo do markdown.

    Suporta escalares (`chave: valor`) e listas, tanto inline (`chave: [a, b]`) quanto
    em bloco (`chave:` seguido de linhas `- item`).
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw = match.group(1)
    body = text[match.end():]
    data: dict[str, object] = {}
    current_key: str | None = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        if _BULLET_RE.match(line) and current_key:
            bucket = data.setdefault(current_key, [])
            if isinstance(bucket, list):
                bucket.append(_BULLET_RE.sub("", line).strip().strip("\"'"))
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if not value:
            data[key] = []
            current_key = key
            continue
        current_key = None
        if value.startswith("[") and value.endswith("]"):
            data[key] = _split_list(value)
        else:
            data[key] = value.strip("\"'")
    return data, body


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _section_key(header: str) -> str | None:
    key = header.strip().lower().rstrip(":")
    key = re.sub(r"^\d+\.\s*", "", key)
    if key in _LIST_SECTIONS:
        return _LIST_SECTIONS[key]
    for name, field in _SECTION_FIELDS.items():
        if name in key:
            return field
    return None


def parse_skill_markdown(text: str, *, source_path: str | Path | None = None) -> SkillSpec:
    """Converte um arquivo Markdown de Skill em `SkillSpec` completo."""
    front, body = parse_frontmatter(text)
    fields: dict[str, list[str]] = {}
    description = str(front.get("description") or "").strip()
    current: str | None = None

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("#"):
            header = line.lstrip("#").strip()
            if header.lower() in {"descrição", "descricao", "description"}:
                current = "description"
                continue
            current = _section_key(header)
            continue
        if not line:
            continue
        if current == "description" and not description:
            description = line
            continue
        if current:
            item = _BULLET_RE.sub("", line).strip()
            if item:
                fields.setdefault(current, []).append(item)

    skill_id = str(front.get("id") or "").strip()
    if not skill_id and source_path is not None:
        skill_id = Path(source_path).stem.lower().replace("-", "_")
    name = str(front.get("name") or "").strip() or skill_id.replace("_", " ").title()
    if not description:
        for paragraph in body.split("\n\n"):
            clean = paragraph.strip()
            if clean and not clean.startswith("#"):
                description = clean[:300]
                break

    metadata: dict[str, object] = {}
    if source_path is not None:
        metadata["source_file"] = str(source_path)

    return SkillSpec(
        id=skill_id,
        name=name,
        description=description or f"Skill carregada de {Path(str(source_path or '')).name}",
        version=str(front.get("version") or "1.0.0"),
        activation_criteria=_as_list(front.get("activation_criteria")) or fields.get("activation_criteria", []),
        prohibited_criteria=_as_list(front.get("prohibited_criteria")) or fields.get("prohibited_criteria", []),
        required_tools=_as_list(front.get("required_tools")) or fields.get("required_tools", []),
        procedures=fields.get("procedures", []),
        validation_rules=fields.get("validation_rules", []),
        risk_factors=_as_list(front.get("risk_factors")) or fields.get("risk_factors", []),
        examples=_as_list(front.get("examples")) or fields.get("examples", []),
        keywords=[k.lower() for k in _as_list(front.get("keywords"))],
        applies_to_kinds=_as_list(front.get("applies_to_kinds")),
        metadata=metadata,
    )


def load_catalog(directory: str | Path | None = None, *, strict: bool = True) -> list[SkillSpec]:
    """Carrega todas as Skills `.md` de um diretório de catálogo.

    Entradas: diretório do catálogo e `strict` (quando `True`, Skills inválidas são
    descartadas e logadas). Saída: lista de `SkillSpec` lidos do catálogo.

    Um arquivo quebrado do catálogo nunca derruba a execução do agente.
    """
    if directory is None:
        directory = default_catalog_dir()
    if directory is None:
        return []
    base = Path(directory)
    if not base.is_dir():
        return []

    skills: list[SkillSpec] = []
    for file_path in sorted(base.glob("**/*.md")):
        if file_path.name.lower() == "readme.md":
            continue
        try:
            skill = parse_skill_markdown(file_path.read_text(encoding="utf-8"), source_path=file_path)
        except Exception as exc:  # pragma: no cover - catálogo corrompido não derruba o agente
            logger.warning("Skill inválida em %s: %s", file_path, exc)
            continue
        errors = skill.validate()
        if errors and strict:
            logger.warning("Skill %s ignorada: %s", file_path.name, errors)
            continue
        skills.append(skill)
    return skills
