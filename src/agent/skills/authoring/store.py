"""
Arquivo: src/agent/skills/authoring/store.py
Nome: store.py
Propósito: instalar, ativar, atualizar, versionar e reverter skills criadas pelo agente.
Responsabilidade: camada de aplicação — ciclo de vida das skills no disco, com histórico e proveniência.
Componentes: SkillStore, InstalledSkill, hash_tree, copy_tree.
Dependências: agent.skills.authoring.layout, agent.skills.authoring.validator, shutil, json.
Observações: instalar nunca executa scripts; a ativação é separada da instalação por desenho.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.skills.authoring.layout import (
    MANIFEST_FILE,
    SKILL_FILE,
    SkillLayout,
    default_manifest,
    now_iso,
    render_manifest,
)
from agent.skills.authoring.validator import ValidationResult, validate_skill

#: ExtensõesZs que nunca são copiadas na instalação.
IGNORED_NAMES = {"__pycache__", ".git", ".DS_Store", ".pytest_cache", "node_modules"}


def hash_tree(root: str | Path) -> str:
    """Calcula o resumo do conteúdo de uma pasta.

    O resumo cobre nome, tamanho e conteúdo de cada arquivo, em ordem estável: duas
    versões com o mesmo resumo têm o mesmo conteúdo.

    Args:
        root: pasta a resumir.

    Returns:
        O resumo hexadecimal (sha256) da pasta.
    """
    digest = hashlib.sha256()
    base = Path(root)
    if not base.exists():
        return digest.hexdigest()
    for path in sorted(p for p in base.rglob("*") if p.is_file()):
        if any(part in IGNORED_NAMES for part in path.parts):
            continue
        digest.update(str(path.relative_to(base)).encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            continue
        digest.update(b"\0")
    return digest.hexdigest()


def copy_tree(source: str | Path, target: str | Path) -> None:
    """Copia uma pasta ignorando artefatos de build.

    Args:
        source: pasta de origem.
        target: pasta de destino.
    """
    base = Path(source)
    destination = Path(target)
    shutil.copytree(
        base,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*IGNORED_NAMES),
    )


def declared_name(source: str | Path) -> str:
    """Nome declarado pela skill na origem, quando existe e é válido.

    O `SKILL.md` declara o nome da competência; a pasta de origem pode ter outro nome
    (por exemplo, `origem` ou `pacote`). A declaração é preferida, desde que siga o
    padrão de nome aceito.

    Args:
        source: pasta da skill de origem.

    Returns:
        O nome declarado, ou string vazia quando não há nome válido.
    """
    from agent.skills.authoring.layout import NAME_RE, SKILL_FILE

    skill_file = Path(source) / SKILL_FILE
    if not skill_file.is_file():
        return ""
    try:
        text = skill_file.read_text(encoding="utf-8")
    except OSError:
        return ""
    from agent.skills.catalog.loader import parse_frontmatter

    front, _ = parse_frontmatter(text)
    for key in ("id", "name"):
        value = str(front.get(key) or "").strip().lower()
        if value and NAME_RE.match(value):
            return value
    return ""


@dataclass
class InstalledSkill:
    """Uma skill instalada no repositório de skills.

    Atributos:
        name: nome da skill (nome da pasta).
        path: pasta da skill.
        manifest: metadados do `manifest.json`.
        enabled: quando `True`, a skill está habilitada para uso.
        state: estado do ciclo de vida.
        version: versão declarada.
        digest: resumo do conteúdo da pasta.
    """

    name: str
    path: str
    manifest: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    state: str = "draft"
    version: str = "1.0.0"
    digest: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Representação serializável da skill instalada.

        Returns:
            Um dicionário com os campos da skill.
        """
        return {
            "name": self.name,
            "path": self.path,
            "manifest": self.manifest,
            "enabled": self.enabled,
            "state": self.state,
            "version": self.version,
            "digest": self.digest,
        }


class SkillStore:
    """Repositório de skills do agente, com ciclo de vida e histórico.

    O repositório é uma pasta no disco (`data/skills` por padrão). Cada skill ocupa
    uma pasta própria, com `SKILL.md` e `manifest.json`.

    Atributos:
        root: pasta que contém as skills instaladas.
    """

    def __init__(self, root: str | Path) -> None:
        """Cria o repositório.

        Args:
            root: pasta que contém as skills instaladas.
        """
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------- leitura

    def path_of(self, name: str) -> Path:
        """Caminho da pasta de uma skill.

        Args:
            name: nome da skill.

        Returns:
            O caminho da pasta da skill.
        """
        return self.root / name

    def read_manifest(self, name: str) -> dict[str, Any]:
        """Lê o manifesto de uma skill instalada.

        Args:
            name: nome da skill.

        Returns:
            O dicionário do manifesto; vazio quando a skill não existe.
        """
        manifest_path = self.path_of(name) / MANIFEST_FILE
        if not manifest_path.is_file():
            return {}
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def list_installed(self) -> list[InstalledSkill]:
        """Lista as skills instaladas.

        Returns:
            A lista de skills, ordenada por nome.
        """
        found: list[InstalledSkill] = []
        if not self.root.is_dir():
            return found
        for entry in sorted(self.root.iterdir()):
            if not entry.is_dir() or not (entry / SKILL_FILE).is_file():
                continue
            manifest = self.read_manifest(entry.name)
            found.append(
                InstalledSkill(
                    name=entry.name,
                    path=str(entry),
                    manifest=manifest,
                    enabled=bool(manifest.get("enabled", True)),
                    state=str(manifest.get("state") or "draft"),
                    version=str(manifest.get("version") or "1.0.0"),
                    digest=hash_tree(entry),
                )
            )
        return found

    def get(self, name: str) -> InstalledSkill | None:
        """Skill instalada pelo nome.

        Args:
            name: nome da skill.

        Returns:
            A skill, ou `None` quando ela não está instalada.
        """
        for item in self.list_installed():
            if item.name == name:
                return item
        return None

    def search(self, query: str, *, limit: int = 20) -> list[InstalledSkill]:
        """Pesquisa skills por nome ou descrição.

        Args:
            query: termo pesquisado.
            limit: quantidade máxima de resultados.

        Returns:
            A lista de skills que casam com o termo.
        """
        needle = (query or "").strip().lower()
        if not needle:
            return self.list_installed()[: max(1, int(limit))]
        hits: list[InstalledSkill] = []
        for item in self.list_installed():
            haystack = " ".join(
                [
                    item.name,
                    item.version,
                    str(item.manifest.get("description") or ""),
                    " ".join(item.manifest.get("keywords") or []),
                ]
            ).lower()
            if needle in haystack:
                hits.append(item)
        return hits[: max(1, int(limit))]

    def validate(self, name: str) -> ValidationResult:
        """Valida uma skill instalada.

        Args:
            name: nome da skill.

        Returns:
            O resultado da validação.
        """
        return validate_skill(self.path_of(name))

    # --------------------------------------------------------------- escrita

    def _write_manifest(self, name: str, manifest: dict[str, Any]) -> None:
        """Grava o manifesto de uma skill.

        Args:
            name: nome da skill.
            manifest: conteúdo do manifesto.
        """
        layout = SkillLayout.of(self.path_of(name))
        layout.manifest.write_text(render_manifest(manifest), encoding="utf-8")

    def install(
        self,
        source: str | Path,
        *,
        name: str | None = None,
        origin: str = "import",
        state: str = "draft",
        force: bool = False,
    ) -> dict[str, Any]:
        """Instala uma skill a partir de uma pasta externa.

        A instalação **copia** o conteúdo: nada da origem é executado. O manifesto é
        criado ou completado, e a primeira entrada do histórico registra a origem.

        Args:
            source: pasta com `SKILL.md`.
            name: nome de instalação; `None` usa o nome da pasta de origem.
            origin: procedência registrada no manifesto.
            state: estado inicial da skill.
            force: quando `True`, sobrescreve uma skill já instalada.

        Returns:
            Um dicionário com o resultado e a skill instalada.
        """
        source_path = Path(source).expanduser().resolve()
        if not (source_path / SKILL_FILE).is_file():
            return {"success": False, "error": f"a origem não tem {SKILL_FILE}: {source_path}"}
        target_name = name or declared_name(source_path) or source_path.name
        target = self.path_of(target_name)
        if target.exists():
            if not force:
                return {
                    "success": False,
                    "error": f"a skill '{target_name}' já está instalada",
                    "hint": "use update ou informe force=true para substituir.",
                }
            shutil.rmtree(target, ignore_errors=True)
        copy_tree(source_path, target)
        manifest = self.read_manifest(target_name) or default_manifest(
            target_name, origin=origin, state=state
        )
        manifest["id"] = target_name
        manifest["name"] = target_name
        manifest["origin"] = origin
        manifest["state"] = state
        manifest.setdefault("enabled", True)
        manifest.setdefault("created_at", now_iso())
        manifest["updated_at"] = now_iso()
        manifest["version"] = str(manifest.get("version") or "1.0.0")
        manifest.setdefault("history", [])
        history = list(manifest.get("history") or [])
        history.append(
            {
                "version": manifest["version"],
                "at": now_iso(),
                "action": "install",
                "origin": origin,
                "digest": hash_tree(target),
                "note": f"instalada a partir de {source_path}",
            }
        )
        manifest["history"] = history
        manifest["scripts"] = self._collect(target, "scripts")
        manifest["references"] = self._collect(target, "references")
        manifest["assets"] = self._collect(target, "assets")
        self._write_manifest(target_name, manifest)
        return {"success": True, "skill": self.get(target_name).as_dict() if self.get(target_name) else {}}

    def _collect(self, root: Path, folder: str) -> list[str]:
        """Lista os arquivos de uma subpasta da skill.

        Args:
            root: pasta da skill.
            folder: nome da subpasta.

        Returns:
            A lista de caminhos relativos.
        """
        base = root / folder
        if not base.is_dir():
            return []
        return [str(path.relative_to(root)) for path in sorted(base.rglob("*")) if path.is_file()]

    def set_state(self, name: str, state: str, *, note: str = "") -> dict[str, Any]:
        """Muda o estado de uma skill no ciclo de vida.

        Args:
            name: nome da skill.
            state: novo estado (`draft`, `validated`, `approved`, `disabled`, `rejected`).
            note: observação registrada no histórico.

        Returns:
            Um dicionário com o resultado.
        """
        installed = self.get(name)
        if installed is None:
            return {"success": False, "error": f"skill não instalada: {name}"}
        manifest = self.read_manifest(name)
        manifest["state"] = state
        manifest["updated_at"] = now_iso()
        history = list(manifest.get("history") or [])
        history.append(
            {
                "version": manifest.get("version", "1.0.0"),
                "at": now_iso(),
                "action": f"state:{state}",
                "digest": installed.digest,
                "note": note,
            }
        )
        manifest["history"] = history
        self._write_manifest(name, manifest)
        return {"success": True, "skill": (self.get(name) or installed).as_dict()}

    def activate(self, name: str) -> dict[str, Any]:
        """Ativa uma skill validada.

        Uma skill inválida não é ativada: o resultado traz os erros de validação.

        Args:
            name: nome da skill.

        Returns:
            Um dicionário com o resultado.
        """
        installed = self.get(name)
        if installed is None:
            return {"success": False, "error": f"skill não instalada: {name}"}
        validation = self.validate(name)
        if not validation.valid:
            return {
                "success": False,
                "error": "a skill não passou na validação",
                "validation": validation.as_dict(),
            }
        manifest = self.read_manifest(name)
        manifest["enabled"] = True
        manifest["state"] = "approved" if manifest.get("state") in {"draft", "validated"} else manifest.get("state")
        manifest["updated_at"] = now_iso()
        history = list(manifest.get("history") or [])
        history.append(
            {
                "version": manifest.get("version", "1.0.0"),
                "at": now_iso(),
                "action": "activate",
                "digest": installed.digest,
                "note": "",
            }
        )
        manifest["history"] = history
        self._write_manifest(name, manifest)
        return {"success": True, "skill": (self.get(name) or installed).as_dict()}

    def deactivate(self, name: str, *, note: str = "") -> dict[str, Any]:
        """Desativa uma skill, sem apagar o conteúdo.

        Args:
            name: nome da skill.
            note: observação registrada no histórico.

        Returns:
            Um dicionário com o resultado.
        """
        installed = self.get(name)
        if installed is None:
            return {"success": False, "error": f"skill não instalada: {name}"}
        manifest = self.read_manifest(name)
        manifest["enabled"] = False
        manifest["state"] = "disabled"
        manifest["updated_at"] = now_iso()
        history = list(manifest.get("history") or [])
        history.append(
            {
                "version": manifest.get("version", "1.0.0"),
                "at": now_iso(),
                "action": "deactivate",
                "digest": installed.digest,
                "note": note,
            }
        )
        manifest["history"] = history
        self._write_manifest(name, manifest)
        return {"success": True, "skill": (self.get(name) or installed).as_dict()}

    def update(self, name: str, source: str | Path, *, version: str | None = None) -> dict[str, Any]:
        """Atualiza uma skill instalada a partir de uma nova versão.

        O conteúdo do usuário é preservado: a versão anterior é arquivada antes da
        troca, e o histórico registra a operação.

        Args:
            name: nome da skill instalada.
            source: pasta com a nova versão.
            version: nova versão; `None` mantém a do manifesto.

        Returns:
            Um dicionário com o resultado.
        """
        installed = self.get(name)
        if installed is None:
            return {"success": False, "error": f"skill não instalada: {name}"}
        source_path = Path(source).expanduser().resolve()
        if not (source_path / SKILL_FILE).is_file():
            return {"success": False, "error": f"a origem não tem {SKILL_FILE}: {source_path}"}
        previous = self.read_manifest(name)
        backup = self.path_of(".versions") / name / f"{previous.get('version', '1.0.0')}-{installed.digest[:8]}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            copy_tree(self.path_of(name), backup)
        target = self.path_of(name)
        for entry in sorted(target.iterdir()):
            if entry.name in {MANIFEST_FILE, SKILL_FILE}:
                continue
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
        copy_tree(source_path, target)
        manifest = self.read_manifest(name) or previous
        manifest["id"] = name
        manifest["version"] = version or str(manifest.get("version") or "1.0.0")
        manifest["updated_at"] = now_iso()
        manifest.setdefault("enabled", True)
        manifest.setdefault("history", [])
        history = list(manifest.get("history") or [])
        history.append(
            {
                "version": manifest["version"],
                "at": now_iso(),
                "action": "update",
                "digest": hash_tree(target),
                "note": f"substituída por {source_path}",
                "previous_digest": installed.digest,
            }
        )
        manifest["history"] = history
        manifest["scripts"] = self._collect(target, "scripts")
        manifest["references"] = self._collect(target, "references")
        manifest["assets"] = self._collect(target, "assets")
        self._write_manifest(name, manifest)
        return {
            "success": True,
            "skill": (self.get(name) or installed).as_dict(),
            "backup": str(backup),
        }

    def rollback(self, name: str, *, version: str | None = None) -> dict[str, Any]:
        """Restaura uma versão anterior de uma skill.

        Args:
            name: nome da skill.
            version: versão a restaurar; `None` restaura a mais recente arquivada.

        Returns:
            Um dicionário com o resultado.
        """
        versions = self.path_of(".versions") / name
        if not versions.is_dir():
            return {"success": False, "error": f"não há versões arquivadas para '{name}'"}
        candidates = sorted((item for item in versions.iterdir() if item.is_dir()), reverse=True)
        if not candidates:
            return {"success": False, "error": f"não há versões arquivadas para '{name}'"}
        chosen = candidates[0]
        if version:
            matches = [item for item in candidates if item.name.startswith(f"{version}-")]
            if not matches:
                return {"success": False, "error": f"versão não arquivada: {version}"}
            chosen = matches[0]
        current = self.path_of(name)
        shutil.rmtree(current, ignore_errors=True)
        copy_tree(chosen, current)
        manifest = self.read_manifest(name)
        manifest["updated_at"] = now_iso()
        history = list(manifest.get("history") or [])
        history.append(
            {
                "version": manifest.get("version", "1.0.0"),
                "at": now_iso(),
                "action": "rollback",
                "digest": hash_tree(current),
                "note": f"restaurada de {chosen.name}",
            }
        )
        manifest["history"] = history
        self._write_manifest(name, manifest)
        return {"success": True, "restored": str(chosen), "skill": (self.get(name).as_dict() if self.get(name) else {})}

    def history(self, name: str) -> dict[str, Any]:
        """Histórico de alterações de uma skill.

        Args:
            name: nome da skill.

        Returns:
            Um dicionário com a lista de entradas do histórico.
        """
        installed = self.get(name)
        if installed is None:
            return {"success": False, "error": f"skill não instalada: {name}"}
        manifest = self.read_manifest(name)
        entries = list(manifest.get("history") or [])
        return {"success": True, "name": name, "history": entries, "count": len(entries)}

    def remove(self, name: str, *, confirm: bool = False) -> dict[str, Any]:
        """Remove uma skill do repositório.

        A remoção é irreversível: ela exige `confirm=True` e guarda uma cópia em
        `.versions` para permitir a recuperação manual.

        Args:
            name: nome da skill.
            confirm: quando `True`, a remoção é executada.

        Returns:
            Um dicionário com o resultado.
        """
        installed = self.get(name)
        if installed is None:
            return {"success": False, "error": f"skill não instalada: {name}"}
        if not confirm:
            return {
                "success": False,
                "error": "confirmação necessária para remover a skill",
                "confirm_required": True,
                "skill": installed.as_dict(),
            }
        backup = self.path_of(".versions") / name / f"removida-{installed.digest[:8]}"
        backup.parent.mkdir(parents=True, exist_ok=True)
        copy_tree(self.path_of(name), backup)
        shutil.rmtree(self.path_of(name), ignore_errors=True)
        return {"success": True, "removed": name, "backup": str(backup)}
