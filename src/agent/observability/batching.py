"""
Arquivo: src/agent/observability/batching.py
Nome: batching.py
Propósito: agrupar fragmentos de texto antes de publicá-los no stream.
Responsabilidade: camada de aplicação — agrupamento por tamanho ou intervalo dos deltas do modelo.
Componentes: DeltaBatcher.
Dependências: asyncio, agent.config (intervalo e tamanho padrão dos lotes).
Observações: `flush()` no fim da operação garante que nenhum fragmento fica para trás.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import lru_cache


@lru_cache(maxsize=1)
def _defaults() -> tuple[int, int]:
    """Devolve os limites padrão de agrupamento de fragmentos."""
    from agent.config import get_settings

    s = get_settings()
    return s.stream_delta_interval_ms, s.stream_delta_max_chars


class DeltaBatcher:
    """Publica o texto acumulado quando passa de `max_chars` ou `interval_ms` depois do primeiro fragmento
    pendente; `flush()` no fim garante que nada fica para trás. O temporizador roda no loop atual e
    herda o contexto de observação."""

    def __init__(
        self,
        publish: Callable[[str], None],
        *,
        interval_ms: int | None = None,
        max_chars: int | None = None,
    ) -> None:
        """Monta o agrupador com os limites de tempo e tamanho."""
        d_interval, d_chars = _defaults()
        self._publish = publish
        self._interval = (d_interval if interval_ms is None else interval_ms) / 1000
        self._max = d_chars if max_chars is None else max_chars
        self._buf: list[str] = []
        self._size = 0
        self._timer: asyncio.TimerHandle | None = None
        self.batches = 0
        self.chars = 0

    def add(self, text: str) -> None:
        """Acumula um fragmento e publica o lote quando o limite de tamanho é atingido.

        Args:
            text: fragmento recebido do modelo.

        Observações:
            Sem laço de eventos em execução, o lote é publicado imediatamente.
        """
        if not text:
            return
        self._buf.append(text)
        self._size += len(text)
        if self._size >= self._max or self._interval <= 0:
            self.flush()
            return
        if self._timer is None:
            try:
                self._timer = asyncio.get_running_loop().call_later(self._interval, self.flush)
            except RuntimeError:
                self.flush()

    def flush(self) -> None:
        """Publica imediatamente o texto acumulado e cancela o temporizador pendente.

        Observações:
            Chamado ao final da operação para que nenhum fragmento fique retido.
        """
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if not self._buf:
            return
        text = "".join(self._buf)
        self._buf.clear()
        self._size = 0
        self.batches += 1
        self.chars += len(text)
        self._publish(text)
