"""
Arquivo: src/agent/skills/catalog/loader.py
Nome: loader.py
Propósito: carregar as Skills do catálogo em Markdown, que é a fonte de verdade das competências.
Responsabilidade: camada de aplicação — leitura de frontmatter e seções do Markdown para `SkillSpec`.
Componentes: default_catalog_dir, catalog_dir, parse_frontmatter, parse_skill_markdown, load_catalog.
Dependências: agent.skills.models.
Observações: um arquivo quebrado do catálogo nunca derruba a execução do agente.

O catálogo `skills/` do repositório é a fonte de verdade das competências profissionais:
cada arquivo `.md` descreve critérios de ativação, proibições, procedimentos, regras de
validação, riscos, ferramentas autorizadas e palavras-chave. Este módulo converte esses
arquivos em `SkillSpec`, de modo que a mesma definição sirva para descoberta, seleção
sob demanda e injeção no prompt.
"""
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
    """Resolve o catálogo a usar: o do projeto, se existir; senão o do repositório.

    Args:
        project_root: raiz do projeto, cujo diretório `skills/` tem precedência.

    Returns:
        O caminho do catálogo, ou `None` quando não há nenhum disponível.
    """
    if project_root:
        candidate = Path(project_root).resolve() / "skills"
        if candidate.is_dir():
            return candidate
    return default_catalog_dir()


def _split_list(value: str) -> list[str]:
    """Converte um valor inline de frontmatter em lista de itens.

    Args:
        value: texto do valor, com ou sem colchetes.

    Returns:
        A lista de itens, sem aspas.
    """
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [item.strip().strip("\"'") for item in value.split(",") if item.strip()]


def parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Separa o frontmatter do corpo do markdown.

    Suporta escalares (`chave: valor`) e listas, tanto inline (`chave: [a, b]`) quanto
    em bloco (`chave:` seguido de linhas `- item`).

    Args:
        text: conteúdo completo do arquivo Markdown.

    Returns:
        Tupla com os campos do frontmatter e o corpo restante.
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
    """Normaliza um valor de frontmatter em lista de textos não vazios.

    Args:
        value: valor lido do frontmatter.

    Returns:
        A lista de itens; vazia quando o valor é ausente.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _section_key(header: str) -> str | None:
    """Identifica o campo do `SkillSpec` correspondente a um cabeçalho de seção.

    Args:
        header: texto do cabeçalho Markdown, sem os `#`.

    Returns:
        O nome do campo, ou `None` quando a seção não é reconhecida.
    """
    key = header.strip().lower().rstrip(":")
    key = re.sub(r"^\d+\.\s*", "", key)
    if key in _LIST_SECTIONS:
        return _LIST_SECTIONS[key]
    for name, field in _SECTION_FIELDS.items():
        if name in key:
            return field
    return None


def parse_skill_markdown(text: str, *, source_path: str | Path | None = None) -> SkillSpec:
    """Converte um arquivo Markdown de Skill em `SkillSpec` completo.

    Args:
        text: conteúdo do arquivo Markdown.
        source_path: caminho do arquivo de origem, usado no identificador e nos metadados.

    Returns:
        A `SkillSpec` correspondente ao arquivo.
    """
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
    """Carrega todas as Skills de um diretório de catálogo.

    Duas formas coexistem no mesmo catálogo:

    1. **Markdown solto** (`skills/*.md`) — a forma histórica do Callidus;
    2. **Pasta de skill** (`skills/<nome>/SKILL.md`) — a forma autoral, com
       `scripts/`, `references/`, `assets/`, `tests/` e `manifest.json`.

    Entradas: diretório do catálogo e `strict` (quando `True`, Skills inválidas são
    descartadas e logadas). Saída: lista de `SkillSpec` lidos do catálogo.

    Um arquivo quebrado do catálogo nunca derruba a execução do agente.

    Args:
        directory: diretório do catálogo; quando ausente, usa o catálogo do repositório.
        strict: quando `True`, skills com contrato inválido são descartadas.

    Returns:
        A lista de skills lidas do catálogo.
    """
    if directory is None:
        directory = default_catalog_dir()
    if directory is None:
        return []
    base = Path(directory)
    if not base.is_dir():
        return []

    skills: list[SkillSpec] = []
    for file_path in sorted(base.glob("*.md")):
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
    for skill in _load_skill_folders(base, strict=strict):
        skills.append(skill)
    return skills


def _load_skill_folders(base: Path, *, strict: bool) -> list[SkillSpec]:
    """Carrega as skills no formato de pasta (`<nome>/SKILL.md`).

    Args:
        base: diretório do catálogo.
        strict: quando `True`, skills com contrato inválido são descartadas.

    Returns:
        A lista de skills carregadas das pastas.
    """
    from agent.skills.authoring.layout import MANIFEST_FILE, SKILL_FILE

    found: list[SkillSpec] = []
    for folder in sorted(item for item in base.iterdir() if item.is_dir()):
        skill_file = folder / SKILL_FILE
        if not skill_file.is_file():
            continue
        try:
            skill = parse_skill_markdown(skill_file.read_text(encoding="utf-8"), source_path=skill_file)
        except Exception as exc:  # pragma: no cover - skill quebrada não derruba o agente
            logger.warning("Skill inválida em %s: %s", skill_file, exc)
            continue
        manifest = _read_manifest(folder / MANIFEST_FILE)
        # O nome da pasta é o identificador canônico da skill; o frontmatter traz o nome
        # de exibição e a versão.
        skill.id = folder.name
        skill.scripts = _list_files(folder, "scripts")
        skill.references = _list_files(folder, "references")
        skill.assets = _list_files(folder, "assets")
        skill.state = str(manifest.get("state") or "draft")
        skill.origin = str(manifest.get("origin") or "catalog")
        if manifest.get("version"):
            skill.version = str(manifest["version"])
        if manifest.get("requires_tools") and not skill.required_tools:
            skill.required_tools = [str(item) for item in manifest["requires_tools"]]
        skill.metadata["manifest"] = manifest
        skill.metadata["skill_root"] = str(folder)
        errors = skill.validate()
        if errors and strict:
            logger.warning("Skill %s ignorada: %s", folder.name, errors)
            continue
        found.append(skill)
    return found


def _read_manifest(path: Path) -> dict[str, object]:
    """Lê o `manifest.json` de uma skill, tolerando arquivo ausente ou quebrado.

    Args:
        path: caminho do manifesto.

    Returns:
        O dicionário lido, ou um dicionário vazio.
    """
    import json

    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _list_files(root: Path, folder: str) -> list[str]:
    """Lista os arquivos de uma subpasta opcional de uma skill.

    Args:
        root: pasta da skill.
        folder: nome da subpasta.

    Returns:
        A lista de caminhos relativos dos arquivos.
    """
    base = root / folder
    if not base.is_dir():
        return []
    return [str(path.relative_to(root)) for path in sorted(base.rglob("*")) if path.is_file()]
