"""
Arquivo: src/agent/knowledge/reliability/security.py
Nome: security.py
Propósito: segurança e privacidade para o Knowledge Engine.
Responsabilidade: camada de infraestrutura — sanitização, validação, controle de acesso.
Componentes: InputSanitizer, CredentialManager, AccessControl, AuditLogger.
Dependências: secrets, hashlib, re, pathlib.
Observações: nunca loga credenciais; sanitiza inputs antes de enviar a provedores externos.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import cryptography.fernet
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


class InputSanitizer:
    """Sanitiza inputs antes de enviar a provedores externos."""

    # Padrões sensíveis para remover/mascarar
    SENSITIVE_PATTERNS = [
        (re.compile(r"(?i)(api[_-]?key|apikey)\s*[:=]\s*[\"']?([a-zA-Z0-9_\-]{20,})[\"']?"), "API_KEY"),
        (re.compile(r"(?i)(secret[_-]?key|secretkey)\s*[:=]\s*[\"']?([a-zA-Z0-9_\-]{20,})[\"']?"), "SECRET_KEY"),
        (re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*[\"']?([^\"'\s]{8,})[\"']?"), "PASSWORD"),
        (re.compile(r"(?i)(token|bearer)\s*[:=]\s*[\"']?([a-zA-Z0-9_\-\.]{20,})[\"']?"), "TOKEN"),
        (re.compile(r"(?i)(authorization)\s*[:=]\s*[\"']?Bearer\s+([a-zA-Z0-9_\-\.]{20,})[\"']?"), "AUTH_TOKEN"),
        (re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "IP_ADDRESS"),
        (re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"), "EMAIL"),
        (re.compile(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b"), "CREDIT_CARD"),
        (re.compile(r"(?i)(aws[_-]?access[_-]?key|aws[_-]?secret)\s*[:=]\s*[\"']?([A-Z0-9]{20,})[\"']?"), "AWS_KEY"),
        (re.compile(r"(?i)(github[_-]?token|gh[_-]?token)\s*[:=]\s*[\"']?([a-zA-Z0-9_]{20,})[\"']?"), "GITHUB_TOKEN"),
    ]

    # Domínios permitidos para URLs
    ALLOWED_DOMAINS = {
        "github.com", "api.github.com", "raw.githubusercontent.com",
        "docs.python.org", "pypi.org", "readthedocs.io",
        "developer.mozilla.org", "stackoverflow.com", "stackexchange.com",
        "google.com", "duckduckgo.com", "bing.com",
        "docs.djangoproject.com", "fastapi.tiangolo.com",
        "sqlalchemy.org", "pydantic.dev",
    }

    def sanitize(self, text: str, replacement: str = "[REDACTED]") -> str:
        """Remove/mascara informações sensíveis do texto."""
        sanitized = text
        for pattern, label in self.SENSITIVE_PATTERNS:
            sanitized = pattern.sub(f"[{label}: {replacement}]", sanitized)
        return sanitized

    def sanitize_dict(self, data: dict, replacement: str = "[REDACTED]") -> dict:
        """Sanitiza todos os valores string em um dict recursivamente."""
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self.sanitize(value, replacement)
            elif isinstance(value, dict):
                result[key] = self.sanitize_dict(value, replacement)
            elif isinstance(value, list):
                result[key] = [
                    self.sanitize_dict(item, replacement) if isinstance(item, dict)
                    else self.sanitize(item, replacement) if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                result[key] = value
        return result

    def validate_url(self, url: str) -> tuple[bool, str]:
        """Valida se URL é segura para acesso."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)

            if parsed.scheme not in ("http", "https"):
                return False, f"Esquema não permitido: {parsed.scheme}"

            domain = parsed.netloc.lower()
            # Remover porta
            if ":" in domain:
                domain = domain.split(":")[0]

            # Verificar se domínio é permitido
            allowed = any(domain == allowed_dom or domain.endswith("." + allowed_dom) for allowed_dom in self.ALLOWED_DOMAINS)

            if not allowed:
                return False, f"Domínio não permitido: {domain}"

            return True, ""
        except Exception as e:
            return False, f"URL inválida: {e}"


class CredentialManager:
    """Gerencia credenciais de forma segura (opcional - requer cryptography)."""

    def __init__(self, key: bytes | None = None) -> None:
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography não instalado. Instale com: pip install cryptography")

        self._key = key or self._generate_key()
        self._fernet = cryptography.fernet.Fernet(self._key)

    def _generate_key(self) -> bytes:
        return cryptography.fernet.Fernet.generate_key()

    def encrypt(self, value: str) -> str:
        """Criptografa valor."""
        encrypted = self._fernet.encrypt(value.encode())
        return encrypted.decode()

    def decrypt(self, encrypted_value: str) -> str:
        """Descriptografa valor."""
        decrypted = self._fernet.decrypt(encrypted_value.encode())
        return decrypted.decode()

    def rotate_key(self, new_key: bytes) -> None:
        """Rotaciona chave (recriptografa valores existentes seria necessário)."""
        self._key = new_key
        self._fernet = cryptography.fernet.Fernet(new_key)


class AccessControl:
    """Controle de acesso para operações do Knowledge Engine."""

    def __init__(self) -> None:
        self._permissions: dict[str, set[str]] = {
            "admin": {"*"},
            "user": {"search", "get", "reuser"},
            "agent": {"search", "get", "reuser", "acquire", "save", "validate"},
        }

    def check_permission(self, role: str, operation: str) -> bool:
        """Verifica se role tem permissão para operação."""
        perms = self._permissions.get(role, set())
        return "*" in perms or operation in perms

    def add_permission(self, role: str, operation: str) -> None:
        """Adiciona permissão para role."""
        if role not in self._permissions:
            self._permissions[role] = set()
        self._permissions[role].add(operation)

    def remove_permission(self, role: str, operation: str) -> None:
        """Remove permissão de role."""
        if role in self._permissions:
            self._permissions[role].discard(operation)


class AuditLogger:
    """Logger de auditoria para operações sensíveis."""

    def __init__(self, log_file: Path | None = None) -> None:
        self.log_file = log_file or Path("logs/knowledge_audit.log")
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(
        self,
        operation: str,
        user_id: str | None,
        project_id: str | None,
        details: dict,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Registra operação de auditoria."""
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "operation": operation,
            "user_id": user_id,
            "project_id": project_id,
            "details": self._sanitize_for_log(details),
            "success": success,
            "error": error,
        }

        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass  # Falha silenciosa no log de auditoria

    def _sanitize_for_log(self, data: dict) -> dict:
        """Sanitiza dados para log."""
        sanitizer = InputSanitizer()
        return sanitizer.sanitize_dict(data)


# Instâncias padrão
input_sanitizer = InputSanitizer()
access_control = AccessControl()
audit_logger = AuditLogger()