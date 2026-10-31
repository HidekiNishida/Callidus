"""
Arquivo: src/agent/knowledge/processing/verify.py
Nome: verify.py
Propósito: verificação de informações técnicas (código, versões, assinaturas, documentação).
Responsabilidade: camada de aplicação — valida fatos antes de armazenar como conhecimento.
Componentes: CodeVerifier, DocVerifier, VersionChecker, VerificationResult.
Dependências: agent.knowledge.models, subprocess, ast, importlib.metadata.
Observações: executa verificações determinísticas; não executa código não confiável.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from agent.knowledge.models import KnowledgeValidationStatus


@dataclass
class VerificationResult:
    """Resultado de uma verificação."""

    verification_kind: str
    passed: bool | None
    method: str
    criteria: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None
    validated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: str = KnowledgeValidationStatus.UNVALIDATED.value


class CodeVerifier:
    """Verifica informações relacionadas a código."""

    @staticmethod
    def verify_python_syntax(code: str) -> VerificationResult:
        """Verifica se código Python é sintaticamente válido."""
        try:
            ast.parse(code)
            return VerificationResult(
                verification_kind="python_syntax",
                passed=True,
                method="ast.parse",
                evidence={"checked": True},
            )
        except SyntaxError as e:
            return VerificationResult(
                verification_kind="python_syntax",
                passed=False,
                method="ast.parse",
                evidence={"error": str(e), "line": e.lineno, "offset": e.offset},
                notes=f"Erro de sintaxe: {e.msg}",
            )

    @staticmethod
    def verify_import_exists(module_name: str, attribute: str | None = None) -> VerificationResult:
        """Verifica se módulo/atributo pode ser importado."""
        try:
            if attribute:
                module = __import__(module_name, fromlist=[attribute])
                getattr(module, attribute)
                evidence = {"module": module_name, "attribute": attribute, "found": True}
            else:
                __import__(module_name)
                evidence = {"module": module_name, "found": True}

            return VerificationResult(
                verification_kind="import_check",
                passed=True,
                method="importlib",
                evidence=evidence,
            )
        except ImportError as e:
            return VerificationResult(
                verification_kind="import_check",
                passed=False,
                method="importlib",
                evidence={"error": str(e), "module": module_name, "attribute": attribute},
                notes=f"Import falhou: {e}",
            )
        except AttributeError as e:
            return VerificationResult(
                verification_kind="import_check",
                passed=False,
                method="importlib",
                evidence={"error": str(e), "module": module_name, "attribute": attribute},
                notes=f"Atributo não encontrado: {e}",
            )

    @staticmethod
    def verify_function_signature(module_name: str, function_name: str, expected_params: list[str] | None = None) -> VerificationResult:
        """Verifica assinatura de função."""
        try:
            module = __import__(module_name, fromlist=[function_name])
            func = getattr(module, function_name)

            import inspect
            sig = inspect.signature(func)
            params = list(sig.parameters.keys())

            evidence = {
                "module": module_name,
                "function": function_name,
                "signature": str(sig),
                "parameters": params,
            }

            if expected_params:
                missing = set(expected_params) - set(params)
                extra = set(params) - set(expected_params)
                if missing or extra:
                    return VerificationResult(
                        verification_kind="function_signature",
                        passed=False,
                        method="inspect.signature",
                        evidence=evidence,
                        notes=f"Parâmetros faltando: {missing}, extras: {extra}",
                    )

            return VerificationResult(
                verification_kind="function_signature",
                passed=True,
                method="inspect.signature",
                evidence=evidence,
            )
        except (ImportError, AttributeError) as e:
            return VerificationResult(
                verification_kind="function_signature",
                passed=False,
                method="inspect.signature",
                evidence={"error": str(e)},
                notes=f"Não foi possível verificar: {e}",
            )

    @staticmethod
    def verify_class_exists(module_name: str, class_name: str, expected_methods: list[str] | None = None) -> VerificationResult:
        """Verifica se classe existe e tem métodos esperados."""
        try:
            module = __import__(module_name, fromlist=[class_name])
            cls = getattr(module, class_name)

            methods = [m for m in dir(cls) if not m.startswith("_")]

            evidence = {
                "module": module_name,
                "class": class_name,
                "methods": methods,
            }

            if expected_methods:
                missing = set(expected_methods) - set(methods)
                if missing:
                    return VerificationResult(
                        verification_kind="class_check",
                        passed=False,
                        method="dir()",
                        evidence=evidence,
                        notes=f"Métodos faltando: {missing}",
                    )

            return VerificationResult(
                verification_kind="class_check",
                passed=True,
                method="dir()",
                evidence=evidence,
            )
        except (ImportError, AttributeError) as e:
            return VerificationResult(
                verification_kind="class_check",
                passed=False,
                method="dir()",
                evidence={"error": str(e)},
                notes=f"Classe não encontrada: {e}",
            )


class DocVerifier:
    """Verifica documentação e referências."""

    @staticmethod
    def verify_url_accessible(url: str, timeout: int = 10) -> VerificationResult:
        """Verifica se URL é acessível (HEAD request)."""
        import urllib.request
        import urllib.error

        try:
            req = urllib.request.Request(url, method="HEAD")
            req.add_header("User-Agent", "Callidus-KnowledgeEngine/1.0")
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return VerificationResult(
                    verification_kind="url_accessibility",
                    passed=200 <= response.status < 400,
                    method="http_head",
                    evidence={
                        "url": url,
                        "status": response.status,
                        "content_type": response.headers.get("Content-Type"),
                    },
                )
        except urllib.error.HTTPError as e:
            return VerificationResult(
                verification_kind="url_accessibility",
                passed=False,
                method="http_head",
                evidence={"url": url, "status": e.code, "reason": e.reason},
                notes=f"HTTP {e.code}: {e.reason}",
            )
        except Exception as e:
            return VerificationResult(
                verification_kind="url_accessibility",
                passed=False,
                method="http_head",
                evidence={"url": url, "error": str(e)},
                notes=f"Erro de conexão: {e}",
            )

    @staticmethod
    def verify_documentation_version(url: str, expected_version: str | None = None) -> VerificationResult:
        """Verifica versão da documentação (tenta extrair de URL ou página)."""
        parsed = urlparse(url)
        version_in_url = None

        # Tentar extrair versão da URL
        version_patterns = [
            r"/v?(\d+\.\d+(?:\.\d+)?)/",
            r"/version/(\d+\.\d+(?:\.\d+)?)/",
            r"version=(\d+\.\d+(?:\.\d+)?)",
        ]
        for pattern in version_patterns:
            match = re.search(pattern, url)
            if match:
                version_in_url = match.group(1)
                break

        evidence = {"url": url, "version_in_url": version_in_url}

        if expected_version and version_in_url:
            passed = version_in_url == expected_version or version_in_url.startswith(expected_version)
            return VerificationResult(
                verification_kind="doc_version",
                passed=passed,
                method="url_pattern",
                evidence=evidence,
                notes=f"Esperado: {expected_version}, encontrado: {version_in_url}" if not passed else None,
            )

        return VerificationResult(
            verification_kind="doc_version",
            passed=version_in_url is not None,
            method="url_pattern",
            evidence=evidence,
        )


class VersionChecker:
    """Verifica versões de pacotes e dependências."""

    @staticmethod
    def check_package_version(package_name: str, min_version: str | None = None, max_version: str | None = None) -> VerificationResult:
        """Verifica versão instalada de pacote Python."""
        try:
            from importlib.metadata import version, PackageNotFoundError

            try:
                installed = version(package_name)
            except PackageNotFoundError:
                return VerificationResult(
                    verification_kind="package_version",
                    passed=False,
                    method="importlib.metadata",
                    evidence={"package": package_name, "installed": None},
                    notes=f"Pacote {package_name} não instalado",
                )

            # Comparar versões
            from packaging import version as pkg_version

            installed_ver = pkg_version.parse(installed)
            evidence = {"package": package_name, "installed": installed}

            if min_version:
                min_ver = pkg_version.parse(min_version)
                if installed_ver < min_ver:
                    return VerificationResult(
                        verification_kind="package_version",
                        passed=False,
                        method="packaging.version",
                        evidence={**evidence, "min_required": min_version},
                        notes=f"Versão {installed} < mínima {min_version}",
                    )

            if max_version:
                max_ver = pkg_version.parse(max_version)
                if installed_ver > max_ver:
                    return VerificationResult(
                        verification_kind="package_version",
                        passed=False,
                        method="packaging.version",
                        evidence={**evidence, "max_allowed": max_version},
                        notes=f"Versão {installed} > máxima {max_version}",
                    )

            return VerificationResult(
                verification_kind="package_version",
                passed=True,
                method="packaging.version",
                evidence=evidence,
            )

        except ImportError:
            # Fallback sem packaging
            try:
                import pkg_resources
                installed = pkg_resources.get_distribution(package_name).version
                return VerificationResult(
                    verification_kind="package_version",
                    passed=True,
                    method="pkg_resources",
                    evidence={"package": package_name, "installed": installed},
                )
            except Exception as e:
                return VerificationResult(
                    verification_kind="package_version",
                    passed=False,
                    method="pkg_resources",
                    evidence={"error": str(e)},
                    notes=f"Erro ao verificar: {e}",
                )

    @staticmethod
    def check_python_version(min_version: tuple[int, int] = (3, 11)) -> VerificationResult:
        """Verifica versão do Python."""
        current = sys.version_info[:2]
        passed = current >= min_version

        return VerificationResult(
            verification_kind="python_version",
            passed=passed,
            method="sys.version_info",
            evidence={
                "current": f"{current[0]}.{current[1]}.{sys.version_info[2]}",
                "required": f"{min_version[0]}.{min_version[1]}",
            },
            notes=f"Python {current[0]}.{current[1]} {'atende' if passed else 'não atende'} mínimo {min_version[0]}.{min_version[1]}",
        )

    @staticmethod
    def check_command_available(command: str, version_flag: str = "--version") -> VerificationResult:
        """Verifica se comando está disponível e opcionalmente sua versão."""
        try:
            result = subprocess.run(
                [command, version_flag],
                capture_output=True,
                text=True,
                timeout=10,
            )
            passed = result.returncode == 0
            version_output = result.stdout.strip() or result.stderr.strip()

            return VerificationResult(
                verification_kind="command_available",
                passed=passed,
                method="subprocess",
                evidence={
                    "command": command,
                    "version_output": version_output[:200],
                    "exit_code": result.returncode,
                },
                notes=f"{command} {'disponível' if passed else 'não encontrado'}",
            )
        except FileNotFoundError:
            return VerificationResult(
                verification_kind="command_available",
                passed=False,
                method="subprocess",
                evidence={"command": command},
                notes=f"Comando {command} não encontrado no PATH",
            )
        except Exception as e:
            return VerificationResult(
                verification_kind="command_available",
                passed=False,
                method="subprocess",
                evidence={"error": str(e)},
                notes=f"Erro ao executar: {e}",
            )


def run_verifications(
    knowledge_item: dict[str, Any],
    verifiers: list[tuple[str, Any]] | None = None,
) -> list[VerificationResult]:
    """Executa verificações padrão para um item de conhecimento."""
    results = []

    # Verificações padrão baseadas no tipo de conhecimento
    kind = knowledge_item.get("kind", "")
    technology = knowledge_item.get("technology", "")
    content = knowledge_item.get("content", "")

    # Verificar sintaxe Python se for código
    if "python" in technology.lower() or "code" in kind.lower():
        results.append(CodeVerifier.verify_python_syntax(content))

    # Verificar imports mencionados
    imports = re.findall(r"(?:from|import)\s+([a-zA-Z_][a-zA-Z0-9_.]*)", content)
    for imp in imports[:10]:  # Limitar
        module = imp.split(".")[0]
        if module not in {"os", "sys", "json", "re", "typing", "datetime", "collections", "pathlib"}:
            results.append(CodeVerifier.verify_import_exists(module))

    # Verificar versão Python
    results.append(VersionChecker.check_python_version())

    # Verificações customizadas
    if verifiers:
        for name, verifier_fn in verifiers:
            try:
                results.append(verifier_fn(knowledge_item))
            except Exception as e:
                results.append(VerificationResult(
                    verification_kind=f"custom_{name}",
                    passed=False,
                    method="custom",
                    evidence={"error": str(e)},
                ))

    return results