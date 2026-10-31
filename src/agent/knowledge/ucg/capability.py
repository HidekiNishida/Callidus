"""
Arquivo: src/agent/knowledge/ucg/capability.py
Nome: capability.py
Propósito: Capability Graph — integra Skills, MCPs e ferramentas como nós do UCG com
descoberta seletiva, dependências, permissões e disponibilidade com TTL.
Responsabilidade: camada de aplicação — transforma os catálogos existentes (skills,
ferramentas e servidores MCP) em nós de capacidade consultáveis pelo UCG, sem criar
novas tabelas nem duplicar registros. Cada capacidade expõe metadados baratos (nome,
descrição, entradas, saídas, pré-requisitos, permissões, custo, confiabilidade) para
que a seleção seja feita antes de carregar o conteúdo integral.
Componentes: CapabilityRef, CapabilityCacheEntry, CapabilityCache, CapabilityResolver,
CapabilityGraphService.
Dependências: agent.knowledge.ucg.model, agent.knowledge.ucg.graph, agent.memory.inspection,
agent.memory.layers, agent.persistence.models, agent.skills.catalog.loader,
agent.skills.models, agent.mcp.manager, agent.tools.registry, agent.tools.contracts,
dataclasses, datetime, typing, uuid.
Observações: não grava dados de negócio; lê de `src/agent/skills/catalog/`,
`agent.tools.registry.ToolRegistry`, `agent.mcp.manager.McpManager` e do banco existente.
A disponibilidade de cada recurso tem TTL configurável e não é confiada indefinidamente.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.knowledge.ucg.graph import UnifiedGraphService
from agent.knowledge.ucg.model import (
    GraphDirection,
    GraphDomain,
    GraphEdgeRef,
    GraphNodeKind,
    GraphNodeRef,
    GraphRelationKind,
    GraphScope,
    GraphStatus,
    to_relation_kind,
)
from agent.memory.inspection import InspectionIndex
from agent.persistence.models import ProjectModel

#: TTL padrão (segundos) para a disponibilidade de uma capacidade no cache.
DEFAULT_AVAILABILITY_TTL_SECONDS = 300

#: Limite padrão de candidatos devolvidos por descoberta seletiva.
DEFAULT_DISCOVERY_LIMIT = 20


@dataclass
class CapabilityRef:
    """Referência leve a uma capacidade do Capability Graph.

    Atributos:
        id: identificador estável da capacidade.
        kind: tipo (`skill`, `mcp`, `tool`).
        name: nome legível.
        description: descrição curta (sem o conteúdo integral).
        domain: domínio do UCG (`capability`).
        source_system: sistema de origem (`skill`, `mcp`, `tool`).
        source_id: identificador na tabela/catálogo de origem.
        project_id: projeto de escopo, quando aplicável.
        version: versão do contrato da capacidade.
        status: status de validade (`active`, `expired`, `superseded`, `blocked`).
        metadata: metadados livres (custo, confiabilidade, permissões, etc.).
        available_at: instante em que a disponibilidade foi aferida pela última vez.
        availability_ttl_seconds: tempo de vida da entrada de disponibilidade em cache.
    """

    id: str
    kind: str
    name: str
    description: str = ""
    domain: GraphDomain = GraphDomain.CAPABILITY
    source_system: str = "capability"
    source_id: str = ""
    project_id: str | None = None
    version: int = 1
    status: GraphStatus = GraphStatus.ACTIVE
    metadata: dict[str, Any] = field(default_factory=dict)
    available_at: datetime | None = None
    availability_ttl_seconds: int = DEFAULT_AVAILABILITY_TTL_SECONDS

    def to_graph_node_ref(self) -> GraphNodeRef:
        """Converte a referência de capacidade para um `GraphNodeRef` do UCG."""
        kind_map = {
            "skill": GraphNodeKind.SKILL,
            "mcp": GraphNodeKind.MCP,
            "tool": GraphNodeKind.TOOL,
            "capability": GraphNodeKind.CAPABILITY,
        }
        return GraphNodeRef(
            id=hash(self.id) & 0xFFFFFFFFFFFFFFFF,
            domain=self.domain,
            kind=kind_map.get(self.kind, GraphNodeKind.CAPABILITY),
            source_system=self.source_system,
            source_id=self.source_id,
            project_id=None,
            scope=GraphScope.PROJECT,
            version=self.version,
            status=self.status,
            metadata=dict(self.metadata),
        )

    @property
    def is_available(self) -> bool:
        """Diz se a capacidade está disponível segundo o TTL do cache."""
        if self.available_at is None:
            return False
        elapsed = (datetime.now(UTC) - self.available_at).total_seconds()
        return elapsed < self.availability_ttl_seconds


@dataclass
class CapabilityCacheEntry:
    """Entrada de cache de disponibilidade de uma capacidade.

    Atributos:
        capability_id: identificador da capacidade.
        available: se estava disponível na última aferição.
        checked_at: instante da aferição.
        ttl_seconds: tempo de vida da entrada.
        reason: motivo da indisponibilidade, quando houver.
    """

    capability_id: str
    available: bool
    checked_at: datetime
    ttl_seconds: int
    reason: str = ""

    def is_stale(self) -> bool:
        """Diz se a entrada expirou segundo o TTL."""
        elapsed = (datetime.now(UTC) - self.checked_at).total_seconds()
        return elapsed >= self.ttl_seconds


class CapabilityCache:
    """Cache em memória da disponibilidade de capacidades.

    Não persiste nada; apenas evita consultas repetidas ao disco e aos servidores MCP
    dentro de um mesmo processo.
    """

    def __init__(self) -> None:
        self._entries: dict[str, CapabilityCacheEntry] = {}

    def get(self, capability_id: str) -> CapabilityCacheEntry | None:
        """Devolve a entrada se existir e não estiver estale."""
        entry = self._entries.get(capability_id)
        if entry is None or entry.is_stale():
            return None
        return entry

    def set(
        self,
        capability_id: str,
        available: bool,
        *,
        ttl_seconds: int = DEFAULT_AVAILABILITY_TTL_SECONDS,
        reason: str = "",
    ) -> CapabilityCacheEntry:
        """Armazena ou atualiza a entrada de disponibilidade."""
        entry = CapabilityCacheEntry(
            capability_id=capability_id,
            available=available,
            checked_at=datetime.now(UTC),
            ttl_seconds=ttl_seconds,
            reason=reason,
        )
        self._entries[capability_id] = entry
        return entry

    def invalidate(self, capability_id: str) -> bool:
        """Remove a entrada do cache."""
        if capability_id in self._entries:
            del self._entries[capability_id]
            return True
        return False

    def invalidate_all(self) -> int:
        """Remove todas as entradas e devolve a quantidade removida."""
        count = len(self._entries)
        self._entries.clear()
        return count


class CapabilityResolver:
    """Resolve nós de capacidade a partir dos catálogos existentes.

    Não cria tabelas. Lê de `SkillSpec` (catálogo de skills), `ToolSpec`
    (registro de ferramentas) e `McpServerConfig`/`McpManager` (servidores MCP).
    """

    def __init__(
        self,
        session: Any,
        project: ProjectModel,
        mcp_manager: Any | None = None,
        tool_registry: Any | None = None,
        cache: CapabilityCache | None = None,
    ) -> None:
        """Cria o resolvedor ligado a um projeto e aos catálogos existentes.

        Args:
            session: sessão SQLAlchemy usada nas consultas.
            project: modelo do projeto.
            mcp_manager: gerenciador MCP opcional (cria um novo quando ausente).
            tool_registry: registro de ferramentas opcional (cria um novo quando ausente).
            cache: cache de disponibilidade opcional.
        """
        self._session = session
        self._project = project
        self._mcp_manager = mcp_manager
        self._tool_registry = tool_registry
        self._cache = cache or CapabilityCache()

    def resolve_skills(self, *, limit: int = DEFAULT_DISCOVERY_LIMIT) -> list[CapabilityRef]:
        """Descobre skills do catálogo como capacidades.

        Args:
            limit: quantidade máxima de skills devolvidas.

        Returns:
            Lista de `CapabilityRef` do tipo `skill`.
        """
        capabilities: list[CapabilityRef] = []
        try:
            from agent.skills.catalog.loader import load_catalog
            from agent.skills.models import SkillSpec

            catalog = load_catalog(str(self._project.root_path)) or []
            for spec in catalog[:limit]:
                if not isinstance(spec, SkillSpec):
                    continue
                capabilities.append(
                    CapabilityRef(
                        id=f"skill:{spec.id}",
                        kind="skill",
                        name=spec.name,
                        description=spec.description or "",
                        source_system="skill",
                        source_id=spec.id,
                        project_id=str(self._project.id),
                        version=1,
                        status=GraphStatus.ACTIVE if spec.state != "disabled" else GraphStatus.BLOCKED,
                        metadata={
                            "activation_criteria": spec.activation_criteria or [],
                            "prohibited_criteria": spec.prohibited_criteria or [],
                            "required_tools": spec.required_tools or [],
                            "procedures": spec.procedures or [],
                            "validation_rules": spec.validation_rules or [],
                            "risk_factors": spec.risk_factors or [],
                            "keywords": spec.keywords or [],
                            "applies_to_kinds": spec.applies_to_kinds or [],
                            "state": spec.state,
                            "origin": spec.origin,
                            "cost_estimate": "medio",
                            "reliability": "alta" if spec.state == "approved" else "media",
                        },
                        available_at=datetime.now(UTC),
                    )
                )
        except Exception:
            # O catálogo de skills não deve bloquear o UCG.
            pass
        return capabilities

    def resolve_tools(self, *, limit: int = DEFAULT_DISCOVERY_LIMIT) -> list[CapabilityRef]:
        """Descobre ferramentas do registro como capacidades.

        Args:
            limit: quantidade máxima de ferramentas devolvidas.

        Returns:
            Lista de `CapabilityRef` do tipo `tool`.
        """
        capabilities: list[CapabilityRef] = []
        try:
            registry = self._tool_registry or _build_default_registry()
            specs = registry.list_tools() if hasattr(registry, "list_tools") else []
            for spec in specs[:limit]:
                capabilities.append(
                    CapabilityRef(
                        id=f"tool:{spec.id}",
                        kind="tool",
                        name=spec.id,
                        description=spec.description or "",
                        source_system="tool",
                        source_id=spec.id,
                        project_id=str(self._project.id),
                        version=1,
                        status=GraphStatus.ACTIVE,
                        metadata={
                            "family": spec.family,
                            "risk": spec.risk,
                            "permissions": spec.permissions or [],
                            "requires": spec.requires or [],
                            "requires_approval": spec.requires_approval,
                            "timeout_seconds": spec.timeout_seconds,
                            "side_effects": spec.side_effects,
                            "verify": spec.verify,
                        },
                        available_at=datetime.now(UTC),
                    )
                )
        except Exception:
            pass
        return capabilities

    def resolve_mcps(self, *, limit: int = DEFAULT_DISCOVERY_LIMIT) -> list[CapabilityRef]:
        """Descobre servidores MCP como capacidades.

        Args:
            limit: quantidade máxima de MCPs devolvidas.

        Returns:
            Lista de `CapabilityRef` do tipo `mcp`.
        """
        capabilities: list[CapabilityRef] = []
        try:
            manager = self._mcp_manager or _build_default_mcp_manager()
            tools = manager.list_tools() if hasattr(manager, "list_tools") else []
            servers = manager.list_servers() if hasattr(manager, "list_servers") else []
            server_enabled = {s.id: s.enabled for s in servers}
            for tool in tools[:limit]:
                server_id = tool.get("server", "")
                enabled = server_enabled.get(server_id, False)
                capabilities.append(
                    CapabilityRef(
                        id=f"mcp:{tool.get('id', tool.get('name', ''))}",
                        kind="mcp",
                        name=tool.get("name", tool.get("id", "")),
                        description=tool.get("description", ""),
                        source_system="mcp",
                        source_id=str(tool.get("id", tool.get("name", ""))),
                        project_id=str(self._project.id),
                        version=1,
                        status=GraphStatus.ACTIVE if enabled else GraphStatus.BLOCKED,
                        metadata={
                            "server": server_id,
                            "input_schema": tool.get("input_schema", {}),
                            "output_schema": tool.get("output_schema", {}),
                            "enabled": enabled,
                            "cost_estimate": "alto",
                            "reliability": "media",
                        },
                        available_at=datetime.now(UTC),
                    )
                )
        except Exception:
            pass
        return capabilities

    def resolve_all(self, *, limit: int = DEFAULT_DISCOVERY_LIMIT) -> list[CapabilityRef]:
        """Descobre todas as capacidades (skills, ferramentas, MCPs).

        Args:
            limit: quantidade máxima total devolvida.

        Returns:
            Lista combinada de `CapabilityRef`, limitada por `limit`.
        """
        all_caps: list[CapabilityRef] = []
        all_caps.extend(self.resolve_skills(limit=limit))
        all_caps.extend(self.resolve_tools(limit=limit))
        all_caps.extend(self.resolve_mcps(limit=limit))
        return all_caps[:limit]


def _build_default_registry() -> Any:
    from agent.tools.registry import build_default_registry

    return build_default_registry()


def _build_default_mcp_manager() -> Any:
    from pathlib import Path

    from agent.mcp.manager import McpManager

    config_path = Path("data/mcp.json")
    if not config_path.is_file():
        config_path = Path("data/providers.yaml")
    return McpManager(config_path)


class CapabilityGraphService:
    """Serviço do Capability Graph integrado ao UCG.

    Expõe as capacidades como nós do UCG, com relações `USES`, `REQUIRES`,
    `SUPPORTS`, `IMPLEMENTS`, `VALIDATED_BY`, `APPLICABLE_TO` e `DISCOVERED_BY`,
    e controle de disponibilidade com TTL.

    Atributos:
        _session: sessão SQLAlchemy usada nas consultas.
        _project: modelo do projeto.
        _graph: serviço de leitura do grafo unificado.
        _resolver: resolvedor de capacidades.
        _cache: cache de disponibilidade.
    """

    def __init__(
        self,
        session: Any,
        project: ProjectModel,
        mcp_manager: Any | None = None,
        tool_registry: Any | None = None,
        cache: CapabilityCache | None = None,
    ) -> None:
        """Cria o serviço ligado a um projeto.

        Args:
            session: sessão SQLAlchemy usada nas consultas.
            project: modelo do projeto.
            mcp_manager: gerenciador MCP opcional.
            tool_registry: registro de ferramentas opcional.
            cache: cache de disponibilidade opcional.
        """
        self._session = session
        self._project = project
        self._graph = UnifiedGraphService(session)
        self._resolver = CapabilityResolver(
            session, project, mcp_manager=mcp_manager, tool_registry=tool_registry, cache=cache
        )
        self._cache = self._resolver._cache

    def discover_capabilities(
        self,
        *,
        objective: str = "",
        requirements: list[str] | None = None,
        limit: int = DEFAULT_DISCOVERY_LIMIT,
    ) -> list[CapabilityRef]:
        """Descobre capacidades relevantes para um objetivo e requisitos.

        A seleção é determinística: filtra por palavras-chave do objetivo e
        requisitos, prioriza estado `approved`, e aplica TTL de disponibilidade.

        Args:
            objective: objetivo da etapa (usado para pontuar relevância).
            requirements: requisitos que a capacidade deve cobrir.
            limit: quantidade máxima devolvida.

        Returns:
            Lista de `CapabilityRef` ordenada por relevância.
        """
        candidates = self._resolver.resolve_all(limit=limit * 3)
        req_text = " ".join(requirements or []).lower()
        obj_text = (objective or "").lower()
        scored: list[tuple[int, CapabilityRef]] = []
        for cap in candidates:
            score = 0
            text = f"{cap.name} {cap.description} {' '.join(cap.metadata.get('keywords', []))} {' '.join(cap.metadata.get('activation_criteria', []))}".lower()
            for word in set(req_text.split()) | set(obj_text.split()):
                if len(word) >= 4 and word in text:
                    score += 1
            if cap.metadata.get("state") == "approved":
                score += 5
            if cap.metadata.get("reliability") == "alta":
                score += 3
            if cap.is_available:
                score += 2
            if score > 0 or not req_text and not obj_text:
                scored.append((score, cap))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [cap for _, cap in scored[:limit]]

    def capability_to_graph_node(self, cap: CapabilityRef) -> GraphNodeRef:
        """Converte uma `CapabilityRef` para `GraphNodeRef` do UCG."""
        return cap.to_graph_node_ref()

    def capability_to_graph_node_ref(self, cap: CapabilityRef) -> GraphNodeRef:
        """Converte uma `CapabilityRef` para `GraphNodeRef` do UCG (alias)."""
        return self.capability_to_graph_node(cap)

    def relate_capability_to_tool(
        self, capability: CapabilityRef, tool_id: str
    ) -> GraphEdgeRef | None:
        """Cria uma relação `CAPABILITY_USES_TOOL` entre uma capacidade e uma ferramenta."""
        target = GraphNodeRef(
            id=hash(tool_id) & 0xFFFFFFFFFFFFFFFF,
            domain=GraphDomain.CAPABILITY,
            kind=GraphNodeKind.TOOL,
            source_system="tool",
            source_id=tool_id,
            project_id=None,
            scope=GraphScope.PROJECT,
            version=1,
            status=GraphStatus.ACTIVE,
        )
        source = capability.to_graph_node_ref()
        if not self._graph.validate_relationship(
            source, GraphRelationKind.CAPABILITY_USES_TOOL, target
        ):
            return None
        return GraphEdgeRef(
            source,
            target,
            GraphRelationKind.CAPABILITY_USES_TOOL,
            metadata={"capability_id": capability.id},
        )

    def refresh_availability(self) -> int:
        """Invalida todo o cache de disponibilidade, forçando reaferição."""
        return self._cache.invalidate_all()

    def available_capabilities(self, *, limit: int = DEFAULT_DISCOVERY_LIMIT) -> list[CapabilityRef]:
        """Devolve capacidades disponíveis segundo o cache de disponibilidade."""
        caps = self._resolver.resolve_all(limit=limit * 2)
        return [cap for cap in caps if cap.is_available][:limit]


__all__ = [
    "CapabilityRef",
    "CapabilityCacheEntry",
    "CapabilityCache",
    "CapabilityResolver",
    "CapabilityGraphService",
    "DEFAULT_AVAILABILITY_TTL_SECONDS",
    "DEFAULT_DISCOVERY_LIMIT",
]
