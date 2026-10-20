"""
Arquivo: src/agent/memory/__init__.py
Nome: __init__.py
Propósito: expor as operações de memória do Callidus (extração, decomposição e sumarização).
Responsabilidade: camada de aplicação — fachada pública do pacote `agent.memory`.
Componentes: decompose_for_use, extract_memory_request, fragments_for_prompt, summarize_text.
Dependências: agent.memory.store.
Observações: as funções devolvem texto pronto para o prompt, não persistem nada.
"""
from agent.memory.store import decompose_for_use, extract_memory_request, fragments_for_prompt, summarize_text

__all__ = ["decompose_for_use", "extract_memory_request", "fragments_for_prompt", "summarize_text"]
