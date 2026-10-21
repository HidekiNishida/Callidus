"""
Arquivo: src/agent/skills/authoring/validator.py
Nome: validator.py
Propósito: validar a integridade de uma skill autoral antes de ela ser ativada.
Responsabilidade: camada de aplicação — checagem de nome, metadados, arquivos referenciados e dependências.
Componentes: ValidationResult, validate_skill, validate_name.
Dependências: agent.skills.authoring.layout, agent.skills.catalog.loader, agent.tools.availability.
Observações: a validação nunca executa os scripts da skill; ela apenas os inspeciona.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.skills.authoring.layout import (
    MANIFEST_FILE,
    NAME_RE,
    SKILL_FILE,
    SkillLayout,
)
from agent.skills.catalog.loader import parse_skill_markdown
from agent.tools.availability import check_requirements


@dataclass
class ValidationResult:
    """Veredito da validação de uma skill.

    Atributos:
        valid: quando `True`, a skill pode ser ativada.
        errors: problemas que impedem a ativação.
        warnings: problemas que não impedem, mas merecem atenção.
        metadata: metadados lidos do `SKILL.md`.
        manifest: metadados lidos do `manifest.json`, quando existir.
        missing_dependencies: dependências externas ausentes.
    """

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    missing_dependencies: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Representação serializável do veredito.

        Returns:
            Um dicionário com o resultado da validação.
        """
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "metadata": self.metadata,
            "manifest": self.manifest,
            "missing_dependencies": self.missing_dependencies,
        }


def validate_name(name: str) -> str | None:
    """Valida o nome de uma skill.

    Args:
        name: nome pedido.

    Returns:
        A mensagem de erro, ou `None` quando o nome é válido.
    """
    if not name or not name.strip():
        return "nome vazio"
    if not NAME_RE.match(name):
        return (
            f"nome inválido: '{name}'. Use apenas minúsculas, números, ponto, hífen ou "
            "sublinhado, começando por letra ou número."
        )
    return None


def validate_skill(root: str | Path) -> ValidationResult:
    """Valida uma pasta de skill.

    A validação cobre: nome da pasta, presença e legibilidade do `SKILL.md`, metadados
    obrigatórios, coerência do `manifest.json`, existência dos arquivos referenciados e
    presença das dependências externas declaradas. Nenhum script é executado.

    Args:
        root: pasta da skill.

    Returns:
        O `ValidationResult` correspondente.
    """
    layout = SkillLayout.of(root)
    result = ValidationResult(valid=False)
    name = layout.root.name
    name_error = validate_name(name)
    if name_error:
        result.errors.append(name_error)
    if not layout.skill_md.is_file():
        result.errors.append(f"falta o arquivo {SKILL_FILE}")
        return result
    try:
        text = layout.skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        result.errors.append(f"não foi possível ler {SKILL_FILE}: {exc}")
        return result
    try:
        spec = parse_skill_markdown(text, source_path=layout.skill_md)
    except Exception as exc:  # pragma: no cover - arquivo quebrado é erro, não exceção
        result.errors.append(f"{SKILL_FILE} inválido: {exc}")
        return result
    result.metadata = {
        "id": spec.id,
        "name": spec.name,
        "description": spec.description,
        "version": spec.version,
        "activation_criteria": spec.activation_criteria,
        "prohibited_criteria": spec.prohibited_criteria,
        "required_tools": spec.required_tools,
        "procedures": spec.procedures,
        "validation_rules": spec.validation_rules,
        "risk_factors": spec.risk_factors,
    }
    for message in spec.validate():
        result.errors.append(message)
    if not spec.activation_criteria:
        result.warnings.append("a skill não declara critérios de ativação")
    if not spec.validation_rules:
        result.warnings.append("a skill não declara critérios de validação")
    if not spec.procedures:
        result.warnings.append("a skill não declara procedimentos")

    manifest: dict[str, Any] = {}
    if layout.manifest.is_file():
        try:
            loaded = json.loads(layout.manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result.errors.append(f"{MANIFEST_FILE} inválido: {exc}")
        else:
            if isinstance(loaded, dict):
                manifest = loaded
                result.manifest = manifest
                state = str(manifest.get("state") or "")
                if state and state not in ("draft", "validated", "approved", "disabled", "rejected"):
                    result.errors.append(f"estado desconhecido no manifesto: {state}")
                declared = str(manifest.get("id") or "")
                if declared and declared != name:
                    result.errors.append(f"o manifesto declara o id '{declared}' e a pasta é '{name}'")
            else:
                result.errors.append(f"{MANIFEST_FILE} não contém um objeto JSON")
    else:
        result.warnings.append(f"sem {MANIFEST_FILE}: a skill será tratada como rascunho")

    referenced = _referenced_files(text, manifest)
    for relative in referenced:
        if not (layout.root / relative).exists():
            result.errors.append(f"arquivo referenciado não existe: {relative}")
    for relative in _listed_files(layout, manifest):
        if not (layout.root / relative).exists():
            result.errors.append(f"arquivo listado no manifesto não existe: {relative}")

    requirements = [f"binary:{item}" for item in (manifest.get("requires_binaries") or [])]
    if requirements:
        availability = check_requirements(requirements)
        result.missing_dependencies = availability.missing
        for missing in availability.missing:
            result.warnings.append(f"dependência ausente: {missing}")
    result.valid = not result.errors
    return result


def _referenced_files(text: str, manifest: dict[str, Any]) -> list[str]:
    """Coleta os arquivos referenciados no `SKILL.md` e no manifesto.

    Args:
        text: conteúdo do `SKILL.md`.
        manifest: conteúdo do `manifest.json`.

    Returns:
        A lista de caminhos relativos referenciados.
    """
    found: list[str] = []
    for key in ("scripts", "references", "assets"):
        for item in manifest.get(key) or []:
            found.append(str(item))
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        candidate = stripped[2:].strip().strip("`").strip()
        for prefix in ("scripts/", "references/", "assets/", "tests/"):
            if candidate.startswith(prefix):
                found.append(candidate)
                break
    return list(dict.fromkeys(found))


def _listed_files(layout: SkillLayout, manifest: dict[str, Any]) -> list[str]:
    """Coleta os arquivos declarados no manifesto.

    Args:
        layout: layout da skill.
        manifest: conteúdo do `manifest.json`.

    Returns:
        A lista de caminhos relativos declarados.
    """
    listed: list[str] = []
    for key in ("scripts", "references", "assets"):
        for item in manifest.get(key) or []:
            listed.append(str(item))
    for folder in (layout.scripts, layout.references, layout.assets, layout.tests):
        if not folder.is_dir():
            continue
        for entry in sorted(folder.rglob("*")):
            if entry.is_file():
                listed.append(str(entry.relative_to(layout.root)))
    return list(dict.fromkeys(listed))


def dependency_report(manifest: dict[str, Any]) -> dict[str, Any]:
    """Relata as dependências de uma skill e o que está ausente.

    Args:
        manifest: conteúdo do `manifest.json`.

    Returns:
        Um dicionário com as dependências exigidas, as ausentes e as dicas de instalação.
    """
    requirements = [f"binary:{item}" for item in (manifest.get("requires_binaries") or [])]
    requirements += [f"module:{item}" for item in (manifest.get("requires_modules") or [])]
    availability = check_requirements(requirements)
    return {
        "required": requirements,
        "missing": availability.missing,
        "hints": availability.hints,
        "details": availability.details,
        "ready": availability.available,
        "tool_present": shutil.which("python") is not None,
    }
