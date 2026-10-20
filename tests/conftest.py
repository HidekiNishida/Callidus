"""
Arquivo: tests/conftest.py
Nome: conftest.py
Propósito: reunir as utilidades compartilhadas pelos testes (transporte HTTP simulado, sem rede).
Responsabilidade: camada de testes — fixtures comuns à suíte.
Componentes: fixture `mock_http`.
Dependências: httpx, pytest.
Observações: o transporte simulado garante que nenhum teste dependa de rede.
"""
from __future__ import annotations

import httpx
import pytest


@pytest.fixture
def mock_http(monkeypatch):
    """Substitui o cliente HTTP do módulo indicado por um transporte simulado (sem rede)."""

    def apply(module: str, handler) -> httpx.MockTransport:
        """Aplica o transporte simulado ao módulo indicado e devolve o transporte instalado."""
        transport = httpx.MockTransport(handler)
        real = httpx.AsyncClient

        def factory(*args, **kwargs):
            """Fabrica um cliente httpx que usa o transporte simulado no lugar da rede."""
            kwargs["transport"] = transport
            return real(*args, **kwargs)

        monkeypatch.setattr(f"agent.providers.{module}.httpx.AsyncClient", factory)
        return transport

    return apply
