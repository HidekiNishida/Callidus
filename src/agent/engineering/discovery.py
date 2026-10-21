"""
Arquivo: src/agent/engineering/discovery.py
Nome: discovery.py
Propósito: identificar a linguagem, as ferramentas e os comandos de um projeto real.
Responsabilidade: camada de infraestrutura — leitura de manifests e derivação dos comandos de build, lint e teste.
Componentes: ProjectInfo, detect_project, read_manifest, discover_commands, manifest_keys.
Dependências: pathlib, tomllib, json.
Observações: a descoberta é somente leitura; ela não executa nada do projeto.
"""
from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Manifests reconhecidos, com a linguagem e o gerenciador que costumam acompanhar.
MANIFESTS: dict[str, tuple[str, str]] = {
    "pyproject.toml": ("python", "pip"),
    "setup.py": ("python", "pip"),
    "requirements.txt": ("python", "pip"),
    "package.json": ("javascript", "npm"),
    "go.mod": ("go", "go"),
    "Cargo.toml": ("rust", "cargo"),
    "pom.xml": ("java", "maven"),
    "build.gradle": ("java", "gradle"),
    "build.gradle.kts": ("kotlin", "gradle"),
    "Gemfile": ("ruby", "bundler"),
    "composer.json": ("php", "composer"),
    "CMakeLists.txt": ("c", "cmake"),
    "Makefile": ("make", "make"),
    "docker-compose.yml": ("docker", "docker"),
    "docker-compose.yaml": ("docker", "docker"),
}

#: Ferramentas usadas por script de um `package.json`.
_NODE_RUNNERS = ("pnpm", "yarn", "npm", "bun")

#: Arquivos que carregam as instruções do projeto para o agente.
INSTRUCTION_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    "README.md",
    ".cursorrules",
)


@dataclass
class ProjectInfo:
    """O que a descoberta encontrou sobre um projeto.

    Atributos:
        root: raiz analisada.
        languages: linguagens detectadas, da mais provável para a menos.
        package_managers: gerenciadores de pacotes encontrados.
        manifests: manifests presentes, com o caminho relativo.
        build_systems: sistemas de build reconhecidos.
        monorepo: quando `True`, o projeto tem mais de um pacote.
        workspaces: diretórios de pacotes, quando o projeto é um monorepo.
        instructions: arquivos de instrução presentes.
        env_files: arquivos de ambiente presentes (nomes apenas).
        package_count: quantidade de pacotes encontrados.
    """

    root: str
    languages: list[str] = field(default_factory=list)
    package_managers: list[str] = field(default_factory=list)
    manifests: list[str] = field(default_factory=list)
    build_systems: list[str] = field(default_factory=list)
    monorepo: bool = False
    workspaces: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    env_files: list[str] = field(default_factory=list)
    package_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Representação serializável da descoberta.

        Returns:
            Um dicionário com os campos do projeto.
        """
        return {
            "root": self.root,
            "languages": self.languages,
            "package_managers": self.package_managers,
            "manifests": self.manifests,
            "build_systems": self.build_systems,
            "monorepo": self.monorepo,
            "workspaces": self.workspaces,
            "instructions": self.instructions,
            "env_files": self.env_files,
            "package_count": self.package_count,
        }


def _safe_read_json(path: Path) -> dict[str, Any]:
    """Lê um JSON sem quebrar a descoberta quando o arquivo está malformado.

    Args:
        path: caminho do arquivo.

    Returns:
        O dicionário lido, ou um dicionário vazio.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _safe_read_toml(path: Path) -> dict[str, Any]:
    """Lê um TOML sem quebrar a descoberta quando o arquivo está malformado.

    Args:
        path: caminho do arquivo.

    Returns:
        O dicionário lido, ou um dicionário vazio.
    """
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def manifest_keys(name: str) -> tuple[str, str]:
    """Linguagem e gerenciador associados a um manifest.

    Args:
        name: nome do arquivo de manifest.

    Returns:
        Tupla com a linguagem e o gerenciador; `("", "")` quando o manifest é desconhecido.
    """
    return MANIFESTS.get(name, ("", ""))


def read_manifest(path: str | Path) -> dict[str, Any]:
    """Lê um manifest de projeto e devolve seus campos de alto nível.

    Args:
        path: caminho do manifest (`pyproject.toml`, `package.json`, ...).

    Returns:
        Um dicionário com `name`, `version`, `scripts` e `dependencies` quando existirem.
    """
    file_path = Path(path)
    suffix = file_path.name.lower()
    if suffix == "package.json":
        data = _safe_read_json(file_path)
        return {
            "name": data.get("name", ""),
            "version": data.get("version", ""),
            "scripts": data.get("scripts", {}) if isinstance(data.get("scripts"), dict) else {},
            "dependencies": sorted((data.get("dependencies") or {}).keys()),
        }
    if suffix == "pyproject.toml":
        data = _safe_read_toml(file_path)
        project = data.get("project") if isinstance(data.get("project"), dict) else {}
        tool = data.get("tool") if isinstance(data.get("tool"), dict) else {}
        scripts = {}
        poetry = tool.get("poetry") if isinstance(tool.get("poetry"), dict) else {}
        if isinstance(poetry.get("scripts"), dict):
            scripts.update(poetry["scripts"])
        return {
            "name": project.get("name", ""),
            "version": project.get("version", ""),
            "scripts": scripts,
            "dependencies": sorted(project.get("dependencies") or []),
            "tools": sorted(tool.keys()),
        }
    if suffix == "cargo.toml":
        data = _safe_read_toml(file_path)
        package = data.get("package") if isinstance(data.get("package"), dict) else {}
        return {
            "name": package.get("name", ""),
            "version": package.get("version", ""),
            "scripts": {},
            "dependencies": sorted((package.get("dependencies") or {}).keys()),
        }
    return {"name": file_path.stem, "version": "", "scripts": {}, "dependencies": []}


def detect_project(root: str | Path) -> ProjectInfo:
    """Analisa um diretório e descreve o projeto encontrado.

    A detecção é somente leitura: nenhum comando do projeto é executado.

    Args:
        root: diretório a analisar.

    Returns:
        A `ProjectInfo` correspondente.
    """
    base = Path(root).expanduser().resolve()
    info = ProjectInfo(root=str(base))
    if not base.is_dir():
        return info
    languages: list[str] = []
    managers: list[str] = []
    build_systems: list[str] = []
    for name, (language, manager) in MANIFESTS.items():
        if not (base / name).exists():
            continue
        info.manifests.append(name)
        if language and language not in languages:
            languages.append(language)
        if manager and manager not in managers:
            managers.append(manager)
        if name in {"Makefile", "CMakeLists.txt", "pom.xml"} and name not in build_systems:
            build_systems.append(name)
    package_json = base / "package.json"
    if package_json.is_file():
        data = _safe_read_json(package_json)
        workspaces = data.get("workspaces")
        if isinstance(workspaces, dict):
            workspaces = workspaces.get("packages")
        if isinstance(workspaces, list) and workspaces:
            info.monorepo = True
            info.workspaces = [str(item) for item in workspaces]
    for name in INSTRUCTION_FILES:
        if (base / name).is_file():
            info.instructions.append(name)
    for entry in sorted(base.glob(".env*")):
        if entry.is_file():
            info.env_files.append(entry.name)
    info.languages = languages
    info.package_managers = managers
    info.build_systems = build_systems
    info.package_count = _count_packages(base)
    return info


def _count_packages(base: Path) -> int:
    """Conta os pacotes de um monorepo.

    Args:
        base: raiz do projeto.

    Returns:
        A quantidade de subdiretórios com manifest próprio.
    """
    count = 0
    for name in ("package.json", "pyproject.toml", "Cargo.toml", "go.mod"):
        for _ in base.glob(f"*/{name}"):
            count += 1
    return count


def _node_runner(base: Path) -> str:
    """Descobre o gerenciador de pacotes JavaScript do projeto.

    Args:
        base: raiz do projeto.

    Returns:
        O nome do gerenciador (`pnpm`, `yarn`, `npm`, `bun`).
    """
    if (base / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (base / "yarn.lock").exists():
        return "yarn"
    if (base / "bun.lockb").exists():
        return "bun"
    return "npm"


def discover_commands(root: str | Path) -> dict[str, Any]:
    """Deriva os comandos de build, lint, teste e execução do projeto.

    Os comandos são retornados como listas de argumentos, prontas para execução sem
    shell — a execução passa pelas ferramentas de comando, que aplicam prazo, diretório
    de trabalho e aprovação.

    Args:
        root: raiz do projeto.

    Returns:
        Um dicionário com `install`, `build`, `lint`, `test`, `run` e a origem de cada um.
    """
    base = Path(root).expanduser().resolve()
    info = detect_project(base)
    commands: dict[str, Any] = {"install": None, "build": None, "lint": None, "test": None, "run": None}
    sources: dict[str, str] = {}
    if "pyproject.toml" in info.manifests or "setup.py" in info.manifests:
        has_pytest = (base / "tests").is_dir() or (base / "pytest.ini").is_file()
        commands["install"] = ["pip", "install", "-e", "."]
        sources["install"] = "pyproject.toml"
        commands["test"] = ["python", "-m", "pytest"] if has_pytest else None
        if has_pytest:
            sources["test"] = "pytest"
        if (base / "ruff.toml").is_file() or (base / ".ruff.toml").is_file():
            commands["lint"] = ["ruff", "check", "."]
            sources["lint"] = "ruff.toml"
        elif (base / "Makefile").is_file():
            commands["lint"] = ["make", "lint"]
            sources["lint"] = "Makefile"
    if "package.json" in info.manifests:
        runner = _node_runner(base)
        scripts = read_manifest(base / "package.json").get("scripts", {})
        commands["install"] = [runner, "install"]
        sources["install"] = f"package.json ({runner})"
        for target, name in (("build", "build"), ("lint", "lint"), ("test", "test"), ("run", "dev")):
            if name in scripts:
                commands[target] = [runner, "run", name]
                sources[target] = f"package.json script:{name}"
    if "go.mod" in info.manifests:
        commands["install"] = ["go", "mod", "download"]
        commands["build"] = ["go", "build", "./..."]
        commands["test"] = ["go", "test", "./..."]
        sources.update({"install": "go.mod", "build": "go.mod", "test": "go.mod"})
    if "Cargo.toml" in info.manifests:
        commands["install"] = ["cargo", "fetch"]
        commands["build"] = ["cargo", "build"]
        commands["test"] = ["cargo", "test"]
        sources.update({"install": "Cargo.toml", "build": "Cargo.toml", "test": "Cargo.toml"})
    if "Makefile" in info.manifests:
        makefile = (base / "Makefile").read_text(encoding="utf-8", errors="replace")
        for target, key in (("test", "test"), ("build", "build"), ("lint", "lint"), ("run", "run")):
            if f"{target}:" in makefile and not commands.get(key):
                commands[key] = ["make", target]
                sources[key] = "Makefile"
    return {
        "project": info.as_dict(),
        "commands": commands,
        "sources": sources,
        "runner": _node_runner(base) if "package.json" in info.manifests else "",
    }
