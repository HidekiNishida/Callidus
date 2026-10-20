"""
Arquivo: src/agent/i18n/__init__.py
Nome: __init__.py
Propósito: expor os utilitários de idioma do Callidus (detecção, instrução e tradução).
Responsabilidade: camada de aplicação — fachada pública do pacote `agent.i18n`.
Componentes: detect_language, language_instruction, translate.
Dependências: agent.i18n.locale.
Observações: a tradução é best-effort: na falta do serviço, o texto original é devolvido.
"""
from agent.i18n.locale import detect_language, language_instruction, translate

__all__ = ["detect_language", "language_instruction", "translate"]
