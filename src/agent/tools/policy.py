"""
Arquivo: src/agent/tools/policy.py
Nome: policy.py
Propósito: decidir se uma ferramenta pode rodar, com que risco e se precisa de aprovação humana.
Responsabilidade: camada de infraestrutura — política de permissões por ferramenta, família e sessão.
Componentes: PolicyDecision, PermissionPolicy, redact, redact_text.
Dependências: agent.tools.contracts.
Observações: a política nega por padrão para risco alto; a aprovação é explícita e fica registrada.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agent.tools.contracts import ToolRisk, risk_above

#: Valores aceitos na configuração de uma regra.
ALLOW = "allow"
DENY = "deny"
ASK = "ask"

#: Padrões de segredo redigidos antes de qualquer log, evento ou relatório.
_SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"(?i)(api[_-]?key|apikey|secret|token|password|passwd|pwd|access[_-]?key)\s*[=:]\s*[\"']?[^\s\"',;]{4,}", r"\1=[REDACTED]"),
    (r"(?i)authorization\s*:\s*(bearer|token|basic)\s+[^\s]+", r"authorization: [REDACTED]"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", "[REDACTED_PRIVATE_KEY]"),
    (r"\b[A-Za-z0-9_\-]{32,}\b(?=\s*==?)", "[REDACTED_TOKEN]"),
)

#: Nomes de variáveis de ambiente cujo valor nunca sai.
SECRET_ENV_HINTS: tuple[str, ...] = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "AUTH",
    "SESSION",
    "COOKIE",
    "PRIVATE",
    "SEGREDO",
    "SENHA",
)


@dataclass(frozen=True)
class PolicyDecision:
    """Veredito da política sobre uma chamada de ferramenta.

    Atributos:
        allowed: quando `True`, a chamada pode ser executada.
        requires_approval: quando `True`, a chamada só roda com aprovação explícita.
        reason: justificativa legível, registrada no evento da ferramenta.
        risk: nível de risco considerado na decisão.
    """

    allowed: bool
    requires_approval: bool
    reason: str
    risk: ToolRisk = ToolRisk.READ


@dataclass
class PermissionPolicy:
    """Política de permissões do agente: o que é liberado, o que exige aprovação, o que é proibido.

    A política é avaliada nesta ordem: regra explícita da ferramenta, regra da família,
    piso de risco e, por fim, a decisão padrão. Uma regra `deny` sempre vence.

    Atributos:
        tool_rules: decisões por identificador de ferramenta (`allow`, `ask`, `deny`).
        family_rules: decisões por família de ferramenta.
        max_auto_risk: nível de risco que o agente pode executar sem pedir aprovação.
        disabled_families: famílias desligadas nesta sessão.
        grants: aprovações concedidas nesta sessão, por ferramenta.
    """

    tool_rules: dict[str, str] = field(default_factory=dict)
    family_rules: dict[str, str] = field(default_factory=dict)
    max_auto_risk: ToolRisk = ToolRisk.WRITE
    disabled_families: set[str] = field(default_factory=set)
    grants: set[str] = field(default_factory=set)

    def disable_family(self, family: str) -> None:
        """Desliga uma família de ferramentas nesta sessão.

        Args:
            family: identificador da família (`system`, `desktop`, `skill`, ...).
        """
        self.disabled_families.add(family)

    def enable_family(self, family: str) -> None:
        """Religa uma família de ferramentas nesta sessão.

        Args:
            family: identificador da família.
        """
        self.disabled_families.discard(family)

    def grant(self, tool_id: str) -> None:
        """Concede aprovação pontual para uma ferramenta nesta sessão.

        Args:
            tool_id: identificador da ferramenta aprovada.
        """
        self.grants.add(tool_id)

    def decide(
        self,
        tool_id: str,
        *,
        risk: ToolRisk = ToolRisk.READ,
        family: str = "",
        approved: bool = False,
    ) -> PolicyDecision:
        """Decide se a chamada pode rodar e se exige aprovação.

        Args:
            tool_id: identificador da ferramenta.
            risk: nível de risco declarado pela ferramenta.
            family: família da ferramenta, quando conhecida.
            approved: quando `True`, o executor já DETém a aprovação do chamador.

        Returns:
            O veredito da política.
        """
        if family and family in self.disabled_families:
            return PolicyDecision(False, False, f"família de ferramentas desligada: {family}", risk)
        rule = self.tool_rules.get(tool_id) or self.family_rules.get(family or "")
        if rule == DENY:
            return PolicyDecision(False, False, f"ferramenta bloqueada pela política: {tool_id}", risk)
        if rule == ASK:
            return PolicyDecision(True, True, f"ferramenta exige aprovação explícita: {tool_id}", risk)
        if rule == ALLOW:
            return PolicyDecision(True, False, f"ferramenta liberada pela política: {tool_id}", risk)
        if tool_id in self.grants or approved:
            return PolicyDecision(True, False, f"aprovação concedida para {tool_id}", risk)
        if risk_above(risk, self.max_auto_risk):
            return PolicyDecision(True, True, f"risco {risk.value} acima do piso automático {self.max_auto_risk.value}", risk)
        return PolicyDecision(True, False, f"risco {risk.value} dentro do piso automático", risk)

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> PermissionPolicy:
        """Constrói a política a partir de um dicionário de configuração.

        Args:
            config: dicionário com `tool_rules`, `family_rules`, `max_auto_risk`,
                `disabled_families` e `grants`.

        Returns:
            A política correspondente; política vazia quando a configuração é ausente.
        """
        config = config or {}
        raw_risk = str(config.get("max_auto_risk") or ToolRisk.WRITE.value)
        risk = ToolRisk(raw_risk) if raw_risk in {item.value for item in ToolRisk} else ToolRisk.WRITE
        return cls(
            tool_rules={str(k): str(v) for k, v in (config.get("tool_rules") or {}).items()},
            family_rules={str(k): str(v) for k, v in (config.get("family_rules") or {}).items()},
            max_auto_risk=risk,
            disabled_families={str(item) for item in (config.get("disabled_families") or [])},
            grants={str(item) for item in (config.get("grants") or [])},
        )

    def to_config(self) -> dict[str, Any]:
        """Serializa a política para configuração.

        Returns:
            Um dicionário com as mesmas chaves aceitas por `from_config`.
        """
        return {
            "tool_rules": dict(self.tool_rules),
            "family_rules": dict(self.family_rules),
            "max_auto_risk": self.max_auto_risk.value,
            "disabled_families": sorted(self.disabled_families),
            "grants": sorted(self.grants),
        }


def redact_text(text: str) -> str:
    """Remove segredos de um texto livre.

    Args:
        text: texto possivelmente containing segredos.

    Returns:
        O texto com os valores de segredo substituídos por `[REDACTED]`.
    """
    if not text:
        return text
    out = text
    for pattern, replacement in _SECRET_PATTERNS:
        out = re.sub(pattern, replacement, out, flags=re.DOTALL)
    return out


def redact(value: Any) -> Any:
    """Remove segredos de uma estrutura de dados qualquer, preservando a forma.

    Strings passam por `redact_text`; dicionários e listas são percorridos; outros tipos
    são devolvidos intactos.

    Args:
        value: estrutura a inspecionar.

    Returns:
        A estrutura com os segredos substituídos.
    """
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value


def is_secret_env(name: str) -> bool:
    """Indica se uma variável de ambiente provavelmente guarda um segredo.

    Args:
        name: nome da variável.

    Returns:
        `True` quando o nome sugere credencial.
    """
    upper = name.upper()
    return any(hint in upper for hint in SECRET_ENV_HINTS)


def tool_policy(settings: Any = None) -> PermissionPolicy:
    """Monta a política de permissões a partir da configuração do processo.

    Args:
        settings: objeto de configuração (`agent.config.Settings`) ou dicionário.

    Returns:
        A política correspondente.
    """
    if settings is None:
        return PermissionPolicy()
    if isinstance(settings, dict):
        config = dict(settings)
    else:
        config = {
            "max_auto_risk": getattr(settings, "tool_max_auto_risk", "write"),
            "disabled_families": getattr(settings, "tool_disabled_families", []) or [],
            "tool_rules": {},
        }
        always = getattr(settings, "tool_always_allowed", []) or []
        never = getattr(settings, "tool_never_allowed", []) or []
        config["tool_rules"] = {str(item): ALLOW for item in always}
        config["tool_rules"].update({str(item): DENY for item in never})
    policy = PermissionPolicy.from_config(config)
    return policy
