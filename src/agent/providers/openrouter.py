# src/agent/providers/openrouter.py — OpenRouter (catálogo de modelos de vários autores)
from __future__ import annotations

from agent.providers.openai_compatible import OpenAICompatibleProvider


class OpenRouterProvider(OpenAICompatibleProvider):
    """OpenRouter fala o formato compatível com OpenAI (`/api/v1/chat/completions`) e acrescenta
    cabeçalhos opcionais de identificação (`HTTP-Referer`, `X-Title`). O modelo é o identificador
    do catálogo do OpenRouter (`autor/modelo`), escolhido pelo operador — a lista de modelos é
    consultada pela API, nunca fixada no código."""

    name = "openrouter"
    default_base_url = "https://openrouter.ai/api/v1"

    def __init__(
        self,
        base_url: str | None = None,
        *,
        model: str | None = None,
        api_key: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 120.0,
        max_retries: int = 1,
        allow_private_hosts: bool = True,
        verify_tls: bool = True,
        referer: str | None = None,
        title: str = "Callidus",
        models_cache_ttl: float = 300.0,
    ) -> None:
        merged: dict[str, str] = {"X-Title": title}
        if referer:
            merged["HTTP-Referer"] = referer
        merged.update(headers or {})
        super().__init__(
            base_url,
            model=model,
            api_key=api_key,
            headers=merged,
            timeout=timeout,
            max_retries=max_retries,
            allow_private_hosts=allow_private_hosts,
            verify_tls=verify_tls,
            name=self.name,
            models_cache_ttl=models_cache_ttl,
        )
