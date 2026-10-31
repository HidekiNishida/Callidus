"""
Arquivo: src/agent/knowledge/learning/__init__.py
Nome: __init__.py
Propósito: exporta a API de aprendizado e validação contínua.
Responsabilidade: camada de aplicação — confidence scoring, pattern detection, improvement suggestions.
"""
from agent.knowledge.learning.confidence import (
    ConfidenceScorer,
    ConfidenceUpdater,
    ConfidenceBreakdown,
    ConfidenceFactors,
    recalculate_confidence,
)
from agent.knowledge.learning.tracker import (
    LearningTracker,
    PatternDetector,
    ImprovementSuggester,
    OutcomeRecord,
    LearningPattern,
    ImprovementSuggestion,
    run_learning_cycle,
)

__all__ = [
    "ConfidenceScorer",
    "ConfidenceUpdater",
    "ConfidenceBreakdown",
    "ConfidenceFactors",
    "recalculate_confidence",
    "LearningTracker",
    "PatternDetector",
    "ImprovementSuggester",
    "OutcomeRecord",
    "LearningPattern",
    "ImprovementSuggestion",
    "run_learning_cycle",
]