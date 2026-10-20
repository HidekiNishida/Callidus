"""
Arquivo: src/agent/providers/http.py
Nome: http.py
Propósito: fornecer o transporte HTTP compartilhado por todos os provedores de inferência.
Responsabilidade: camada de infraestrutura — política de conexão, retry, tratamento de erro e streaming.
Componentes: HttpClientConfig, validate_base_url, client_kwargs, redact, map_http_error, get_json, post_json, stream_lines, sse_payloads.
Dependências: httpx, agent.providers.base.
Observações: só falha anterior ao processamento do servidor é repetida; streaming nunca é repetido.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx

from agent.providers.base import (
    ProviderAuthError,
    ProviderConfigError,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)

DEFAULT_TIMEOUT = 120.0
# Só o que falha antes de o servidor processar a requisição é repetido: nada de reenviar
# inferência que pode já ter sido cobrada (500 depois do processamento, timeout do cliente).
RETRYABLE_STATUS = {429, 502, 503, 504}
_RETRY_BACKOFF = 0.25

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9._\-]{12,}"),
    re.compile(r"\bsk-ant-[A-Za-z0-9._\-]{12,}"),
    re.compile(r"\bAIza[A-Za-z0-9._\-]{12,}"),
)


def redact(text: str, secrets: Iterable[str | None] = ()) -> str:
    """Tira segredos de uma mensagem de log/erro: chaves explícitas e formatos conhecidos.

    Args:
        text: texto a inspecionar.
        secrets: credenciais conhecidas, substituídas literalmente.

    Returns:
        O texto sem as credenciais encontradas.
    """
    out = text or ""
    for secret in secrets:
        if secret and len(secret) >= 6:
            out = out.replace(secret, "***")
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + "***", out)
    return out


def _is_private_address(host: str) -> bool:
    """Indica se um endereço IP é interno (privado, loopback, link-local, reservado ou multicast).

    Args:
        host: endereço IP a classificar.

    Returns:
        `True` quando o endereço não é público.
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def validate_base_url(url: str, *, allow_private_hosts: bool = True) -> str:
    """Valida a URL base de um provedor. Endereços privados só são recusados quando o operador
    pede (`allow_private_hosts=False`): Ollama e llama.cpp legítimos rodam em `localhost`/LAN.

    Args:
        url: URL base informada na configuração.
        allow_private_hosts: quando `False`, recusa hosts que resolvem para endereços internos.

    Returns:
        A URL validada, sem barra final.

    Raises:
        ProviderConfigError: quando a URL é vazia, usa outro esquema, não tem host, embute credencial
            ou resolve para um endereço interno proibido.
    """
    raw = (url or "").strip()
    if not raw:
        raise ProviderConfigError("URL base do provedor está vazia")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ProviderConfigError(f"URL base do provedor deve usar http ou https: '{raw}'")
    if not parsed.hostname:
        raise ProviderConfigError(f"URL base do provedor sem host: '{raw}'")
    if parsed.username or parsed.password:
        raise ProviderConfigError("URL base do provedor não pode conter usuário/senha: use cabeçalho de autenticação")
    if not allow_private_hosts:
        host = parsed.hostname
        addresses: list[str] = []
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
            addresses = [info[4][0] for info in infos]
        except socket.gaierror:
            addresses = []
        if any(_is_private_address(address) for address in addresses):
            raise ProviderConfigError(
                f"Host do provedor resolve para endereço interno e `allow_private_hosts` está desligado: '{host}'"
            )
    return raw.rstrip("/")


@dataclass
class HttpClientConfig:
    """Política HTTP comum: tempo limite, cabeçalhos, credencial e política de retry."""

    base_url: str
    timeout: float = DEFAULT_TIMEOUT
    # A credencial não aparece no `repr` nem em dumps da configuração.
    api_key: str | None = field(default=None, repr=False)
    headers: dict[str, str] = field(default_factory=dict)
    max_retries: int = 1
    backoff: float = _RETRY_BACKOFF
    allow_private_hosts: bool = True
    verify_tls: bool = True
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"

    def resolved_base_url(self) -> str:
        """URL base validada segundo a política de hosts privados.

        Returns:
            A URL base sem barra final.

        Raises:
            ProviderConfigError: quando a URL base é inválida.
        """
        return validate_base_url(self.base_url, allow_private_hosts=self.allow_private_hosts)

    def resolved_headers(self) -> dict[str, str]:
        """Cabeçalhos das requisições, com a credencial aplicada no cabeçalho configurado.

        Returns:
            O dicionário de cabeçalhos enviado em cada requisição.
        """
        headers = {"Content-Type": "application/json"}
        headers.update(self.headers or {})
        if self.api_key:
            headers[self.auth_header] = f"{self.auth_scheme} {self.api_key}".strip()
        return headers

    def secrets(self) -> list[str]:
        """Credenciais conhecidas, para serem removidas das mensagens de erro.

        Returns:
            Lista com a credencial configurada, quando houver.
        """
        return [self.api_key] if self.api_key else []


def client_kwargs(config: HttpClientConfig) -> dict[str, Any]:
    """Argumentos de construção do `httpx.AsyncClient` (redirecionamento desligado por padrão)."""
    return {
        "timeout": config.timeout,
        "headers": config.resolved_headers(),
        "follow_redirects": False,
        "verify": config.verify_tls,
    }


def _response_excerpt(response: httpx.Response | None, limit: int = 240) -> str:
    """Trecho inicial do corpo da resposta, para compor mensagens de erro.

    Args:
        response: resposta HTTP; `None` quando não há corpo disponível.
        limit: tamanho máximo do trecho.

    Returns:
        O trecho do corpo, com espaços normalizados.
    """
    if response is None:
        return ""
    try:
        body = response.text
    except Exception:  # pragma: no cover - corpo já consumido
        return ""
    body = " ".join(body.split())
    return body[:limit]


def map_http_error(
    exc: Exception,
    *,
    label: str,
    secrets: Iterable[str | None] = (),
    response: httpx.Response | None = None,
) -> ProviderError:
    """Converte exceção HTTP em erro de provedor com causa explícita (sem vazar credencial).

    Args:
        exc: exceção levantada pela biblioteca HTTP.
        label: nome do provedor, usado no prefixo da mensagem.
        secrets: credenciais a remover da mensagem.
        response: resposta HTTP associada, quando houver.

    Returns:
        O erro de provedor correspondente à falha.
    """
    detail = redact(str(exc), secrets)
    if isinstance(exc, httpx.TimeoutException):
        return ProviderTimeoutError(f"{label}: tempo esgotado ({detail})")
    if isinstance(exc, httpx.ConnectError):
        return ProviderConnectionError(f"{label} indisponível: {detail}")
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        excerpt = redact(_response_excerpt(exc.response), secrets)
        if status in (401, 403):
            return ProviderAuthError(
                f"{label}: falha de autenticação (HTTP {status}). Verifique a credencial configurada."
            )
        if status == 429:
            return ProviderRateLimitError(
                f"{label}: limite de uso atingido (HTTP 429). Tente novamente mais tarde. {excerpt}".strip()
            )
        if status >= 500:
            return ProviderError(f"{label}: erro do servidor (HTTP {status}). {excerpt}".strip())
        return ProviderError(f"{label}: requisição recusada (HTTP {status}). {excerpt}".strip())
    if isinstance(exc, json.JSONDecodeError):
        return ProviderResponseError(f"{label}: resposta não é JSON válido ({detail})")
    if isinstance(exc, httpx.HTTPError):
        return ProviderError(f"{label}: falha na requisição ({detail})")
    return ProviderError(f"{label}: {detail or type(exc).__name__}")


def _retryable(exc: ProviderError) -> bool:
    """Indica se o erro vale uma retentativa.

    Args:
        exc: erro de provedor mapeado.

    Returns:
        `True` para conexão recusada e limite de uso, que são falhas transitórias.
    """
    return isinstance(exc, (ProviderConnectionError, ProviderRateLimitError))


async def _with_retry(
    operation,
    *,
    label: str,
    secrets: Iterable[str | None],
    max_retries: int,
    backoff: float,
):
    """Executa uma operação HTTP repetindo apenas falhas transitórias.

    Args:
        operation: corrotina que executa a requisição.
        label: nome do provedor, usado no prefixo do erro.
        secrets: credenciais a remover das mensagens.
        max_retries: número de retentativas permitidas.
        backoff: intervalo base entre tentativas, em segundos.

    Returns:
        O resultado da operação.

    Raises:
        ProviderError: quando a falha não é repetível ou as tentativas se esgotam.
    """
    attempts = max(0, int(max_retries)) + 1
    last: ProviderError | None = None
    for attempt in range(attempts):
        try:
            return await operation()
        except httpx.HTTPError as exc:
            last = map_http_error(exc, label=label, secrets=secrets)
        except json.JSONDecodeError as exc:
            raise map_http_error(exc, label=label, secrets=secrets) from exc
        if not _retryable(last) or attempt == attempts - 1:
            raise last
        await asyncio.sleep(backoff * (2**attempt))
    raise last  # pragma: no cover - laço sempre retorna ou levanta


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    label: str,
    secrets: Iterable[str | None] = (),
    max_retries: int = 1,
    backoff: float = _RETRY_BACKOFF,
) -> Any:
    """Executa um GET e devolve o corpo JSON.

    Args:
        client: cliente HTTP a usar.
        url: URL a consultar.
        label: nome do provedor, usado no prefixo do erro.
        secrets: credenciais a remover das mensagens.
        max_retries: número de retentativas permitidas.
        backoff: intervalo base entre tentativas, em segundos.

    Returns:
        O corpo JSON da resposta.

    Raises:
        ProviderError: quando a requisição falha.
    """
    async def operation():
        """Executa a requisição HTTP e devolve a resposta tipada do provedor."""
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()

    return await _with_retry(operation, label=label, secrets=secrets, max_retries=max_retries, backoff=backoff)


async def post_json(
    client: httpx.AsyncClient,
    url: str,
    body: dict[str, Any],
    *,
    label: str,
    secrets: Iterable[str | None] = (),
    max_retries: int = 1,
    backoff: float = _RETRY_BACKOFF,
) -> Any:
    """Executa um POST e devolve o corpo JSON.

    Args:
        client: cliente HTTP a usar.
        url: URL a consultar.
        body: corpo JSON da requisição.
        label: nome do provedor, usado no prefixo do erro.
        secrets: credenciais a remover das mensagens.
        max_retries: número de retentativas permitidas.
        backoff: intervalo base entre tentativas, em segundos.

    Returns:
        O corpo JSON da resposta.

    Raises:
        ProviderError: quando a requisição falha.
    """
    async def operation():
        """Executa a requisição HTTP e devolve a resposta tipada do provedor."""
        resp = await client.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    return await _with_retry(operation, label=label, secrets=secrets, max_retries=max_retries, backoff=backoff)


async def stream_lines(
    client: httpx.AsyncClient,
    url: str,
    body: dict[str, Any],
    *,
    label: str,
    secrets: Iterable[str | None] = (),
) -> Iterator[str]:
    """Linhas do corpo de uma resposta em streaming (JSON por linha ou SSE). Sem retry: uma
    transmissão pela metade não pode ser repetida sem custo duplicado.

    Args:
        client: cliente HTTP a usar.
        url: URL da requisição.
        body: corpo JSON da requisição.
        label: nome do provedor, usado no prefixo do erro.
        secrets: credenciais a remover das mensagens.

    Yields:
        Cada linha do corpo da resposta.

    Raises:
        ProviderError: quando a requisição ou a leitura do corpo falha.
    """
    try:
        async with client.stream("POST", url, json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                yield line
    except httpx.HTTPError as exc:
        raise map_http_error(exc, label=label, secrets=secrets) from exc
    except json.JSONDecodeError as exc:
        raise map_http_error(exc, label=label, secrets=secrets) from exc


def sse_payloads(lines: Iterable[str]) -> Iterator[str]:
    """Extrai o payload de eventos SSE (`data: ...`), ignorando comentários e linhas vazias.

    Args:
        lines: linhas do corpo da resposta.

    Yields:
        O payload de cada evento SSE.
    """
    for line in lines:
        text = line.strip()
        if not text or text.startswith(":"):
            continue
        if not text.startswith("data:"):
            continue
        payload = text[5:].strip()
        if payload:
            yield payload
