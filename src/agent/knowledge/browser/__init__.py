"""
Arquivo: src/agent/knowledge/browser/__init__.py
Nome: __init__.py
Propósito: exportar a API de inteligência de navegador.
Responsabilidade: camada de infraestrutura — sessões autenticadas, serviços de IA, extração.
"""
"""
Arquivo: src/agent/knowledge/browser/__init__.py
Nome: __init__.py
Propósito: exporta a API de inteligência de navegador.
Responsabilidade: camada de infraestrutura — sessões autenticadas, serviços de IA, extração.
"""
from agent.knowledge.browser.session import BrowserProfile, AuthenticatedBrowserSession
from agent.knowledge.browser.ai_services import (
    AIServiceBase,
    ChatGPTService,
    GeminiService,
    ClaudeService,
    AIServiceManager,
    AIResponse,
)
from agent.knowledge.browser.extraction import ContentExtractor, ExtractedContent, extract_from_url, extract_search_results

__all__ = [
    "BrowserProfile",
    "AuthenticatedBrowserSession",
    "AIServiceBase",
    "ChatGPTService",
    "GeminiService",
    "ClaudeService",
    "AIServiceManager",
    "AIResponse",
    "ContentExtractor",
    "ExtractedContent",
    "extract_from_url",
    "extract_search_results",
]