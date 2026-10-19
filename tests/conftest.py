# tests/conftest.py — utilidades compartilhadas pelos testes
from __future__ import annotations

import httpx
import pytest


@pytest.fixture
def mock_http(monkeypatch):
    """Substitui o cliente HTTP do módulo indicado por um transporte simulado (sem rede)."""

    def apply(module: str, handler) -> httpx.MockTransport:
        transport = httpx.MockTransport(handler)
        real = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = transport
            return real(*args, **kwargs)

        monkeypatch.setattr(f"agent.providers.{module}.httpx.AsyncClient", factory)
        return transport

    return apply
