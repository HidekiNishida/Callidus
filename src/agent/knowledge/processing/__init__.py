"""
Arquivo: src/agent/knowledge/processing/__init__.py
Nome: __init__.py
Propósito: exportar a API de processamento de conhecimento.
Responsabilidade: camada de aplicação — normalização, comparação, síntese, verificação.
"""
"""
Arquivo: src/agent/knowledge/processing/__init__.py
Nome: __init__.py
Propósito: exporta a API de processamento de conhecimento.
Responsabilidade: camada de aplicação — normalização, comparação, síntese, verificação.
"""
from agent.knowledge.processing.normalize import (
    NormalizedSource,
    ResultNormalizer,
    normalize_search_result,
    deduplicate_sources,
)
from agent.knowledge.processing.compare import (
    SourceComparator,
    ComparisonResult,
    find_consensus,
    find_divergences,
)
from agent.knowledge.processing.synthesize import (
    KnowledgeSynthesizer,
    SynthesisResult,
    SynthesisSection,
    Citation,
    generate_synthesis,
)
from agent.knowledge.processing.verify import (
    CodeVerifier,
    DocVerifier,
    VersionChecker,
    VerificationResult,
    run_verifications,
)

__all__ = [
    "NormalizedSource",
    "ResultNormalizer",
    "normalize_search_result",
    "deduplicate_sources",
    "SourceComparator",
    "ComparisonResult",
    "find_consensus",
    "find_divergences",
    "KnowledgeSynthesizer",
    "SynthesisResult",
    "SynthesisSection",
    "Citation",
    "generate_synthesis",
    "CodeVerifier",
    "DocVerifier",
    "VersionChecker",
    "VerificationResult",
    "run_verifications",
]