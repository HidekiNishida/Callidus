"""
Arquivo: src/agent/intelligence/__init__.py
Nome: __init__.py
Propósito: expor a camada de inteligência operacional do Callidus (telemetria, analytics, grafo cognitivo, benchmarks, diagnósticos).
Responsabilidade: camada de aplicação — fachada pública do pacote `agent.intelligence`.
Componentes: TelemetryService, AnalyticsService, CognitiveGraph, BenchmarkEngine, DiagnosticEngine.
Dependências: agent.intelligence.telemetry, agent.intelligence.analytics, agent.intelligence.graph, agent.intelligence.benchmarks, agent.intelligence.diagnostics.
Observações: nenhum subsistema depende de modelo de linguagem para cálculos determinísticos.
"""
from agent.intelligence.analytics import AnalyticsService
from agent.intelligence.benchmarks import BenchmarkEngine
from agent.intelligence.diagnostics import DiagnosticEngine
from agent.intelligence.graph import CognitiveGraph
from agent.intelligence.telemetry import TelemetryService

__all__ = [
    "AnalyticsService",
    "BenchmarkEngine",
    "CognitiveGraph",
    "DiagnosticEngine",
    "TelemetryService",
]
