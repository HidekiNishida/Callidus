"""
Arquivo: src/agent/skills/authoring/layout.py
Nome: layout.py
Propósito: definir a estrutura de pasta, o `SKILL.md` e o `manifest.json` de uma skill autoral.
Responsabilidade: camada de aplicação — contrato de formato das skills criadas pelo agente.
Componentes: SKILL_FILE, MANIFEST_FILE, SUBDIRS, SkillLayout, skill_dir, render_skill_md, default_manifest, render_manifest.
Dependências: json, pathlib, re.
Observações: o formato é compatível com o padrão aberto Agent Skills; `SKILL.md` é o contrato.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: Arquivo que carrega o contrato da skill.
SKILL_FILE = "SKILL.md"

#: Arquivo que carrega o metadado estruturado da skill.
MANIFEST_FILE = "manifest.json"

#: Subpastas opcionais de uma skill.
SUBDIRS = ("scripts", "references", "assets", "tests")

#: Estados possíveis de uma skill ao longo do ciclo de vida.
STATES = ("draft", "validated", "approved", "disabled", "rejected")

#: Formato aceito para o nome de pasta de uma skill.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def now_iso() -> str:
    """Instante atual em ISO 8601, com fuso horário.

    Returns:
        A data e horacurrentes no formato ISO.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class SkillLayout:
    """As pastas e os arquivos que compõem uma skill.

    Atributos:
        root: pasta da skill.
        skill_md: caminho do `SKILL.md`.
        manifest: caminho do `manifest.json`.
        scripts: pasta de scripts.
        references: pasta de referências.
        assets: pasta de recursos.
        tests: pasta de testes.
    """

    root: Path
    skill_md: Path
    manifest: Path
    scripts: Path
    references: Path
    assets: Path
    tests: Path

    @classmethod
    def of(cls, root: str | Path) -> SkillLayout:
        """Monta o layout a partir da pasta da skill.

        Args:
            root: pasta da skill.

        Returns:
            O layout correspondente.
        """
        base = Path(root)
        return cls(
            root=base,
            skill_md=base / SKILL_FILE,
            manifest=base / MANIFEST_FILE,
            scripts=base / "scripts",
            references=base / "references",
            assets=base / "assets",
            tests=base / "tests",
        )

    def ensure(self) -> SkillLayout:
        """Cria a pasta da skill e as subpastas opcionais.

        Returns:
            O próprio layout, para encadeamento.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        for folder in (self.scripts, self.references, self.assets, self.tests):
            folder.mkdir(parents=True, exist_ok=True)
        return self

    def as_dict(self) -> dict[str, Any]:
        """Representação serializável do layout.

        Returns:
            Um dicionário com os caminhos das pastas e dos arquivos.
        """
        return {
            "root": str(self.root),
            "skill_md": str(self.skill_md),
            "manifest": str(self.manifest),
            "scripts": str(self.scripts),
            "references": str(self.references),
            "assets": str(self.assets),
            "tests": str(self.tests),
        }


def skill_dir(root: str | Path, name: str) -> Path:
    """Caminho da pasta de uma skill dentro de um repositório de skills.

    Args:
        root: pasta que contém as skills.
        name: nome da skill.

    Returns:
        O caminho da pasta da skill.
    """
    return Path(root) / name


def render_skill_md(
    name: str,
    description: str,
    *,
    version: str = "1.0.0",
    activation: list[str] | None = None,
    prohibited: list[str] | None = None,
    tools: list[str] | None = None,
    procedures: list[str] | None = None,
    validation: list[str] | None = None,
    risks: list[str] | None = None,
    prerequisites: list[str] | None = None,
    error_handling: list[str] | None = None,
) -> str:
    """Gera o `SKILL.md` de uma skill nova.

    O frontmatter segue o padrão Agent Skills (`name`, `description`, `version`,
    `allowed-tools`, `metadata`); o corpo traz os critérios e os procedimentos.

    Args:
        name: nome da skill.
        description: descrição objetiva, orientada ao modelo.
        version: versão inicial.
        activation: critérios de utilização.
        prohibited: situações em que a skill não deve ser usada.
        tools: ferramentas permitidas.
        procedures: passos a seguir.
        validation: critérios de conclusão.
        risks: riscos a controlar.
        prerequisites: pré-requisitos de ambiente.
        error_handling: como tratar erros.

    Returns:
        O conteúdo do arquivo `SKILL.md`.
    """
    front: list[str] = [
        "---",
        f"name: {name}",
        f"description: {description}",
        f"version: {version}",
    ]
    if tools:
        front.append("allowed-tools: " + ", ".join(tools))
    front.append("metadata:")
    front.append("  origin: agent")
    front.append(f"  created_at: {now_iso()}")
    front.append("---")
    body: list[str] = [
        "",
        f"# {name}",
        "",
        "## Descrição",
        "",
        description,
        "",
        "## Critérios de ativação",
        "",
    ]
    body += [f"- {item}" for item in (activation or ["Use quando a tarefa corresponde a esta competência."])]
    body += ["", "## Quando não utilizar", ""]
    body += [f"- {item}" for item in (prohibited or ["Não use para tarefas fora do escopo descrito acima."])]
    body += ["", "## Pré-requisitos", ""]
    body += [f"- {item}" for item in (prerequisites or ["Nenhum pré-requisito além do ambiente padrão do Callidus."])]
    body += ["", "## Ferramentas permitidas", ""]
    body += [f"- {item}" for item in (tools or ["Nenhuma ferramenta específica."])]
    body += ["", "## Procedimentos", ""]
    body += [f"{index}. {item}" for index, item in enumerate(procedures or ["Descreva aqui o procedimento."], 1)]
    body += ["", "## Tratamento de erros", ""]
    body += [f"- {item}" for item in (error_handling or ["Registre a falha e não prossiga sem evidência."])]
    body += ["", "## Critérios de validação", ""]
    body += [f"- {item}" for item in (validation or ["A tarefa foi concluída e verificada."])]
    body += ["", "## Riscos", ""]
    body += [f"- {item}" for item in (risks or ["Nenhum risco específico declarado."])]
    body += [""]
    return "\n".join(front + body)


def default_manifest(
    name: str,
    *,
    version: str = "1.0.0",
    description: str = "",
    origin: str = "agent",
    state: str = "draft",
    permissions: list[str] | None = None,
    requires_tools: list[str] | None = None,
    requires_binaries: list[str] | None = None,
) -> dict[str, Any]:
    """Manifesto inicial de uma skill.

    Args:
        name: nome da skill.
        version: versão inicial.
        description: descrição da skill.
        origin: procedência (`agent`, `user`, `import`).
        state: estado inicial do ciclo de vida.
        permissions: permissões mínimas pedidas pela skill.
        requires_tools: ferramentas de que a skill precisa.
        requires_binaries: executáveis de que a skill precisa.

    Returns:
        O dicionário do manifesto.
    """
    return {
        "id": name,
        "name": name,
        "version": version,
        "description": description,
        "state": state,
        "origin": origin,
        "enabled": True,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "permissions": list(permissions or []),
        "requires_tools": list(requires_tools or []),
        "requires_binaries": list(requires_binaries or []),
        "scripts": [],
        "references": [],
        "assets": [],
        "history": [],
    }


def render_manifest(manifest: dict[str, Any]) -> str:
    """Serializa o manifesto de uma skill.

    Args:
        manifest: dicionário do manifesto.

    Returns:
        O texto JSON do manifesto, com indentação e quebra de linha final.
    """
    return json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
