"""
Arquivo: src/agent/automation/timezones.py
Nome: timezones.py
Propósito: calcular instantes a partir de horários locais, fusos e horário de verão.
Responsabilidade: camada de domínio — conversão entre hora de parede local e instante UTC.
Componentes: resolve_timezone, to_utc, localize, next_cron_occurrence, occurrences_between, seconds_until, floor_minute, add_interval.
Dependências: croniter, zoneinfo (stdlib).
Observações: o carimbo persistido é sempre UTC; o fuso vive na definição da automação.

Cálculo de instantes a partir de horários locais.

Regras que este módulo garante:

- O carimbo persistido é sempre UTC; o fuso vive na definição da automação.
- Hora local **inexistente** (o "pulou" do horário de verão): o disparo acontece no
  primeiro instante existente depois do buraco — nunca em um instante que não existe.
- Hora local **ambígua** (repetida na virada): vence o primeiro instante (o mais
  cedo), como é esperado de um agendamento.
- Fuso inválido é recusado na validação, não no disparo.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

__all__ = [
    "localize",
    "next_cron_occurrence",
    "resolve_timezone",
    "to_utc",
]


def resolve_timezone(name: str | None) -> str:
    """Normaliza e valida um nome de fuso. `None`/vazio vira `UTC`.

    Args:
        name: nome do fuso, como `America/Sao_Paulo`.

    Returns:
        O nome do fuso validado.

    Raises:
        ValueError: quando o fuso não existe.
    """
    clean = (name or "UTC").strip()
    if not clean:
        return "UTC"
    try:
        ZoneInfo(clean)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"fuso horário inválido: {clean}") from exc
    return clean


def to_utc(value: datetime) -> datetime:
    """Normaliza um datetime para UTC. Sem fuso, assume UTC.

    Args:
        value: instante de entrada.

    Returns:
        O mesmo instante, em UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def localize(naive_local: datetime, tz_name: str) -> datetime:
    """Converte um horário local (sem fuso) no instante UTC correspondente.

    - Horário inexistente (spring forward): avança pelo buraco até o primeiro
      instante existente.
    - Horário ambíguo (fall back): devolve o primeiro instante (o mais cedo).

    Args:
        naive_local: horário local, sem fuso.
        tz_name: nome do fuso local.

    Returns:
        O instante UTC correspondente.

    Raises:
        ValueError: quando o fuso é inválido.
    """
    tz = ZoneInfo(resolve_timezone(tz_name))
    candidate = naive_local.replace(tzinfo=tz, fold=0)
    roundtrip = candidate.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)
    if roundtrip != naive_local:
        # O horário local não existe: calcula o buraco e avança.
        off_before = naive_local.replace(tzinfo=tz, fold=0).utcoffset()
        off_after = naive_local.replace(tzinfo=tz, fold=1).utcoffset()
        gap = (off_after or off_before) - (off_before or off_after)
        shifted = naive_local + gap
        return shifted.replace(tzinfo=tz, fold=0).astimezone(timezone.utc)
    return candidate.astimezone(timezone.utc)


def next_cron_occurrence(
    expression: str,
    tz_name: str,
    after: datetime,
    *,
    limit: int = 1,
) -> list[datetime]:
    """Próximas ocorrências de uma expressão cron, em UTC.

    O cálculo é feito no relógio local (a expressão cron descreve hora de parede) e
    só depois convertido para UTC — é isso que faz o gatilho acompanhar o horário de
    verão do fuso escolhido.

    Args:
        expression: expressão cron da automação.
        tz_name: fuso em que a expressão é interpretada.
        after: instante de referência.
        limit: quantidade de ocorrências devolvidas.

    Returns:
        A lista de instantes UTC, em ordem crescente.

    Raises:
        ValueError: quando o fuso ou a expressão cron é inválida.
    """
    tz = ZoneInfo(resolve_timezone(tz_name))
    base = to_utc(after).astimezone(tz).replace(tzinfo=None)
    try:
        iterator = croniter(expression, base)
    except (ValueError, KeyError) as exc:
        raise ValueError(f"expressão cron inválida: {expression}") from exc
    out: list[datetime] = []
    for _ in range(max(1, limit)):
        nxt = iterator.get_next(datetime)
        out.append(localize(nxt, tz_name))
    return out


def occurrences_between(
    expression: str,
    tz_name: str,
    start: datetime,
    end: datetime,
    *,
    limit: int = 100,
) -> list[datetime]:
    """Ocorrências de cron dentro de uma janela (UTC, inclusiva no início).

    Args:
        expression: expressão cron da automação.
        tz_name: fuso em que a expressão é interpretada.
        start: início da janela.
        end: fim da janela.
        limit: quantidade máxima de ocorrências devolvidas.

    Returns:
        A lista de instantes UTC dentro da janela.

    Raises:
        ValueError: quando o fuso ou a expressão cron é inválida.
    """
    tz = ZoneInfo(resolve_timezone(tz_name))
    base = to_utc(start).astimezone(tz).replace(tzinfo=None)
    try:
        iterator = croniter(expression, base)
    except (ValueError, KeyError) as exc:
        raise ValueError(f"expressão cron inválida: {expression}") from exc
    out: list[datetime] = []
    for _ in range(limit):
        nxt = iterator.get_next(datetime)
        if nxt < base:
            continue
        instant = localize(nxt, tz_name)
        if instant > to_utc(end):
            break
        out.append(instant)
    return out


def seconds_until(now: datetime, target: datetime) -> float:
    """Segundos entre dois instantes (pode ser negativo).

    Args:
        now: instante de referência.
        target: instante alvo.

    Returns:
        A diferença em segundos.
    """
    return (to_utc(target) - to_utc(now)).total_seconds()


def floor_minute(moment: datetime) -> datetime:
    """Arredonda para o minuto — usado para detectar o mesmo minuto de disparo.

    Args:
        moment: instante de entrada.

    Returns:
        O instante, em UTC, sem segundos nem microssegundos.
    """
    return to_utc(moment).replace(second=0, microsecond=0)


def add_interval(moment: datetime, seconds: int) -> datetime:
    """Soma um intervalo a um instante, em UTC.

    Args:
        moment: instante de referência.
        seconds: quantidade de segundos a somar.

    Returns:
        O novo instante, em UTC.
    """
    return to_utc(moment) + timedelta(seconds=seconds)
