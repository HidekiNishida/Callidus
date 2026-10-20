"""
Arquivo: src/agent/automation/triggers/temporal.py
Nome: temporal.py
Propósito: implementar os gatilhos temporais de automação (uma vez, cron e intervalo).
Responsabilidade: camada de domínio — cálculo dos instantes elegíveis de cada recorrência.
Componentes: OnceTrigger, CronTrigger, IntervalTrigger, DailyAtTrigger.
Dependências: agent.automation.contracts, agent.automation.enums, agent.automation.timezones.
Observações: todos devolvem instantes UTC; a expressão cron descreve hora de parede do fuso escolhido.

Gatilhos temporais: uma vez, cron e intervalo.

Todos devolvem instantes UTC. A expressão cron descreve hora de parede do fuso
escolhido, então a virada do horário de verão é respeitada.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from agent.automation.contracts import TriggerSpec
from agent.automation.enums import TriggerKind
from agent.automation.timezones import (
    add_interval,
    localize,
    next_cron_occurrence,
    occurrences_between,
    to_utc,
)


class OnceTrigger:
    """Execução única em um instante determinado."""

    kind = TriggerKind.ONCE

    def __init__(self, spec: TriggerSpec) -> None:
        """Cria o gatilho de execução única.

        Args:
            spec: especificação do gatilho.

        Raises:
            ValueError: quando a definição não traz `run_at`.
        """
        if spec.run_at is None:
            raise ValueError("gatilho 'once' exige run_at")
        self._at = to_utc(spec.run_at)
        self._tz = spec.timezone

    def next_occurrence(self, after: datetime) -> datetime | None:
        """Instante único, quando ainda está no futuro.

        Args:
            after: instante de referência.

        Returns:
            O instante da execução, ou `None` quando já passou.
        """
        return self._at if self._at > to_utc(after) else None

    def occurrences(self, start: datetime, end: datetime, *, limit: int = 100) -> list[datetime]:
        """Instantes elegíveis na janela.

        Args:
            start: início da janela.
            end: fim da janela.
            limit: quantidade máxima devolvida.

        Returns:
            Uma lista com o instante da execução, quando ele está na janela.
        """
        if start <= self._at <= end:
            return [self._at]
        return []


class CronTrigger:
    """Recorrência por expressão cron (5 ou 6 campos)."""

    kind = TriggerKind.CRON

    def __init__(self, spec: TriggerSpec) -> None:
        """Cria o gatilho de recorrência por cron.

        Args:
            spec: especificação do gatilho.

        Raises:
            ValueError: quando a expressão cron está ausente ou é inválida.
        """
        expression = (spec.cron or "").strip()
        if not expression:
            raise ValueError("gatilho 'cron' exige expressão")
        self._expression = expression
        self._tz = spec.timezone
        # Falha cedo (ao montar o gatilho) e não no meio do disparo.
        next_cron_occurrence(expression, self._tz, datetime.now())

    def next_occurrence(self, after: datetime) -> datetime | None:
        """Devolve a próxima ocorrência do gatilho a partir de um instante."""
        return next_cron_occurrence(self._expression, self._tz, after)[0]

    def occurrences(self, start: datetime, end: datetime, *, limit: int = 100) -> list[datetime]:
        """Devolve as próximas ocorrências do gatilho dentro de uma janela."""
        return occurrences_between(self._expression, self._tz, start, end, limit=limit)


class IntervalTrigger:
    """Recorrência por intervalo fixo, contado a partir do horário de referência."""

    kind = TriggerKind.INTERVAL

    def __init__(self, spec: TriggerSpec) -> None:
        """Cria o gatilho de intervalo fixo.

        Args:
            spec: especificação do gatilho.

        Raises:
            ValueError: quando `interval_seconds` está ausente ou não é positivo.
        """
        seconds = int(spec.interval_seconds or 0)
        if seconds <= 0:
            raise ValueError("gatilho 'interval' exige interval_seconds > 0")
        self._seconds = seconds
        self._tz = spec.timezone
        self._anchor = to_utc(spec.run_at) if spec.run_at else None

    def next_occurrence(self, after: datetime) -> datetime | None:
        """Próximo instante elegível depois do instante informado.

        Args:
            after: instante de referência.

        Returns:
            O próximo instante, em UTC.
        """
        moment = to_utc(after)
        if self._anchor is not None and moment < self._anchor:
            return self._anchor
        if self._anchor is not None:
            elapsed = (moment - self._anchor).total_seconds()
            steps = int(elapsed // self._seconds) + 1
            return self._anchor + timedelta(seconds=steps * self._seconds)
        return moment + timedelta(seconds=self._seconds)

    def occurrences(self, start: datetime, end: datetime, *, limit: int = 100) -> list[datetime]:
        """Instantes elegíveis na janela.

        Args:
            start: início da janela.
            end: fim da janela.
            limit: quantidade máxima devolvida.

        Returns:
            A lista de instantes UTC dentro da janela.
        """
        out: list[datetime] = []
        if self._anchor is not None and start <= self._anchor <= end:
            out.append(self._anchor)
            cursor = self._anchor
        else:
            cursor = to_utc(start)
        while len(out) < limit:
            nxt = add_interval(cursor, self._seconds)
            if nxt > to_utc(end):
                break
            out.append(nxt)
            cursor = nxt
        return out


class DailyAtTrigger:
    """Atalho: todo dia, no horário local informado (ex.: `09:30` no fuso da automação)."""

    kind = TriggerKind.CRON

    def __init__(self, spec: TriggerSpec) -> None:
        """Cria o gatilho diário a partir do horário `HH:MM` informado.

        Args:
            spec: especificação do gatilho.

        Raises:
            ValueError: quando o horário diário está ausente ou é inválido.
        """
        at = (spec.cron or "").strip()
        if not at:
            raise ValueError("gatilho diário exige HH:MM")
        hour, _, minute = at.partition(":")
        self._expression = f"{int(minute)} {int(hour)} * * *"
        self._tz = spec.timezone

    def next_occurrence(self, after: datetime) -> datetime | None:
        """Próximo instante elegível depois do instante informado.

        Args:
            after: instante de referência.

        Returns:
            O próximo instante, em UTC.
        """
        return next_cron_occurrence(self._expression, self._tz, after)[0]

    def occurrences(self, start: datetime, end: datetime, *, limit: int = 100) -> list[datetime]:
        """Instantes elegíveis na janela.

        Args:
            start: início da janela.
            end: fim da janela.
            limit: quantidade máxima devolvida.

        Returns:
            A lista de instantes UTC dentro da janela.
        """
        return occurrences_between(self._expression, self._tz, start, end, limit=limit)


__all__ = ["CronTrigger", "DailyAtTrigger", "IntervalTrigger", "OnceTrigger", "localize"]
