"""
Arquivo: src/agent/engineering/__init__.py
Nome: __init__.py
Propósito: expor a caixa de ferramentas de engenharia de software do agente.
Responsabilidade: camada de infraestrutura — ponto de entrada estável para o agente.
Componentes: reexports de `discovery`, `git`, `quality`, `dependency_graph`, `context_retrieval`.
Dependências: agent.engineering.*.
Observações: a descoberta só lê; a execução de comandos é feita com a política de permissões.
"""
from __future__ import annotations

from agent.engineering.context_retrieval import (
    ComponentScorer,
    ContextRetriever,
    IncrementalContextManager,
    RetrievalQuery,
    RetrievalResult,
)
from agent.engineering.dependency_graph import (
    DependencyGraph,
    EdgeInfo,
    ImpactAnalyzer,
    ImpactResult,
    NodeInfo,
    compute_transitive_closure,
)
from agent.engineering.discovery import detect_project, discover_commands, read_manifest
from agent.engineering.git import git_branch, git_diff, git_log, git_status
from agent.engineering.quality import run_check, summarize_test_output

__all__ = [
    "ComponentScorer",
    "ContextRetriever",
    "DependencyGraph",
    "EdgeInfo",
    "ImpactAnalyzer",
    "ImpactResult",
    "IncrementalContextManager",
    "NodeInfo",
    "RetrievalQuery",
    "RetrievalResult",
    "compute_transitive_closure",
    "detect_project",
    "discover_commands",
    "git_branch",
    "git_diff",
    "git_log",
    "git_status",
    "read_manifest",
    "run_check",
    "summarize_test_output",
]
