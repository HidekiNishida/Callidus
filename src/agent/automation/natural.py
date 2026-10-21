"""
Arquivo: src/agent/automation/natural.py
Nome: natural.py
Propósito: entender horários, datas e recorrências escritos em linguagem natural.
Responsabilidade: camada de domínio — interpretação temporal; não grava nada e não decide política.
Componentes: ScheduleIntent, parse_schedule, describe_trigger, DEFAULT_TIMEZONE.
Dependências: agent.automation.contracts, agent.automation.enums, agent.automation.timezones.
Observações: o texto do usuário vira um `TriggerSpec` validado; nada é inventado quando falta informação.

O usuário fala em português: "todos os dias às 9h", "amanhã às 14h", "a cada quatro horas".

Este módulo traduz esse texto em um `TriggerSpec` — o mesmo contrato que a API HTTP
recebe — para que o chat **não** dependa de o usuário saber escrever cron. O
resultado é sempre validado pelo contrato existente (`TriggerSpec`) e calculado
pelo mecanismo temporal existente (`agent.automation.timezones`), inclusive no
horário de verão.

Três regras que o módulo garante:

1. **Não inventa.** Texto ambíguo ("de manhã", "toda semana" sem dia) devolve uma
   pergunta, não um horário escolhido.
2. **Não converte recorrência em outra.** "Toda sexta" continua semanal; "a cada
   4 horas" continua intervalo.
3. **Não confia no relógio do modelo.** A resolução usa a data e a hora reais do
   processo e o fuso configurado.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from agent.automation.contracts import TriggerSpec
from agent.automation.enums import TriggerKind
from agent.automation.timezones import localize, resolve_timezone

# Fuso usado quando o usuário não configurou nenhum. É o fuso do Brasil — o
# Callidus é escrito em português e a instalação local é a referência.
DEFAULT_TIMEZONE = "America/Sao_Paulo"

_WEEKDAY_NAMES: dict[str, int] = {
    "segunda": 0,
    "terca": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "sabado": 5,
    "domingo": 6,
}

_WEEKDAY_LABELS = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)

_MONTH_NAMES: dict[str, int] = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

# Números escritos por extenso: "a cada quatro horas" é tão comum quanto "a cada 4 horas".
_NUMBER_WORDS: dict[str, float] = {
    "meia": 0.5,
    "uma": 1,
    "um": 1,
    "duas": 2,
    "dois": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
}

_NUMBER_PATTERN = r"\d{1,3}|" + "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))

# "de manhã", "mais tarde": imprecisos o bastante para mudar o agendamento.
_VAGUE_MARKERS = (
    "de manha",
    "a tarde",
    "a noite",
    "mais tarde",
    "cedo",
    "no fim do dia",
    "durante o dia",
    "a qualquer hora",
)

_INTERVAL_UNITS = {
    "minuto": 60,
    "minutos": 60,
    "hora": 3600,
    "horas": 3600,
    "dia": 86400,
    "dias": 86400,
    "semana": 604800,
    "semanas": 604800,
}

_RE_INTERVAL = re.compile(
    rf"\ba\s+cada\s+(?P<n>{_NUMBER_PATTERN})\s*(?P<u>minutos?|horas?|dias?|semanas?)\b"
)
_RE_EVERY = re.compile(
    rf"\bde\s+(?P<a>{_NUMBER_PATTERN})\s+em\s+(?P<b>{_NUMBER_PATTERN})\s*(?P<u>horas?|minutos?)\b"
)
_RE_HOURLY = re.compile(r"\bde\s+hora\s+em\s+hora\b")
_RE_MONTH_END = re.compile(
    r"\b(?:no\s+|na\s+|todo\s+|cada\s+)?ultimo\s+dia\s+(?:d[eo]\s+)?(?:cada\s+|todo\s+o\s+|todo\s+)?mes\b"
)
_RE_WEEKDAY = re.compile(r"\b(segunda|terca|quarta|quinta|sexta|sabado|domingo)(-feira)?s?\b")
_RE_EVERY_DAY = re.compile(
    r"\b(?:todos\s+os\s+dias|todo\s+dia|diaria|dariamente|daily|every\s+day)\b"
)
_RE_EVERY_HOUR = re.compile(r"\b(?:toda\s+hora|every\s+hour|de\s+hora\s+em\s+hora)\b")
_RE_EVERY_WEEK = re.compile(r"\b(?:toda\s+semana|todo\s+semana|semanalmente|weekly)\b")
_RE_EVERY_MONTH = re.compile(r"\b(?:todo\s+mes|todos\s+os\s+meses|monthly)\b")
_RE_TIME = re.compile(
    r"(?P<h>\d{1,2})\s*(?:(?:horas?|hrs?)\s*(?P<m1>\d{2})?|h\s*(?P<m1b>\d{2})?|[:.](?P<m2>\d{2})(?::\d{2})?)"
)
_RE_TIME_AT = re.compile(r"\b(?:as|à|as)\s+(?P<h>\d{1,2})\b")
_RE_TOMORROW = re.compile(r"\bdepois\s+de\s+amanha\b|\bafter\s+tomorrow\b")
_RE_TODAY = re.compile(r"\bhoje\b|\btoday\b")
_RE_TOMORROW_1 = re.compile(r"\bamanha\b|\btomorrow\b")
_RE_IN = re.compile(
    rf"\b(?:daqui\s+a|em)\s*(?P<n>{_NUMBER_PATTERN})\s*(?P<u>minutos?|horas?|dias?|semanas?)\b"
)
_RE_DAY_MONTH = re.compile(r"\b(?:dia\s+)?(\d{1,2})\s+de\s+([a-z]+)\b")
_RE_DAY_OF_MONTH = re.compile(r"\bdia\s+(\d{1,2})\b")
_RE_SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")
_RE_NEXT_WEEKDAY = re.compile(r"\b(?:na\s+|no\s+|para\s+)?pr[oó]xim[oa]\s+([a-z]+)\b")
_RE_NEXT_WEEK = re.compile(r"\bpr[oó]xim[ao]\s+semana\b")
_RE_RECURRING = re.compile(r"\b(?:toda|todo|todas|todos)\b")


@dataclass(frozen=True)
class ScheduleIntent:
    """Resultado da interpretação de um texto de agendamento.

    Atributos:
        kind: `once`, `cron`, `interval`, `ambiguous` ou `unparsed`.
        trigger: gatilho validado, quando o texto foi suficiente.
        summary: descrição legível do que foi resolvido.
        question: pergunta a fazer ao usuário quando falta informação.
    """

    kind: str
    trigger: TriggerSpec | None = None
    summary: str = ""
    question: str | None = None

    @property
    def resolved(self) -> bool:
        """Diz se o texto virou um gatilho utilizável.

        Returns:
            `True` quando há `TriggerSpec` pronto para persistir.
        """
        return self.trigger is not None

    @property
    def needs_clarification(self) -> bool:
        """Diz se falta informação para o usuário.

        Returns:
            `True` quando a interpretação devolve uma pergunta.
        """
        return self.question is not None


def _strip_accents(text: str) -> str:
    """Remove acentos e baixa a caixa, para comparar texto em português.

    Args:
        text: texto de entrada.

    Returns:
        O texto normalizado.
    """
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _now_in(timezone: str) -> datetime:
    """Instante atual no fuso informado.

    Args:
        timezone: nome do fuso.

    Returns:
        O instante atual, com o fuso aplicado.
    """
    return datetime.now(ZoneInfo(resolve_timezone(timezone)))


def _amount(text: str) -> float:
    """Valor numérico de um número escrito por extenso ou em dígitos.

    Args:
        text: trecho com o número.

    Returns:
        O valor numérico.
    """
    clean = (text or "").strip()
    if clean.isdigit():
        return int(clean)
    return _NUMBER_WORDS.get(clean, 0.0)


def _match_time(text: str) -> tuple[int, int] | None:
    """Procura um horário de parede no texto ("9h", "8h30", "14:00", "às 9").

    Args:
        text: texto normalizado (sem acentos, minúsculo).

    Returns:
        Tupla `(hora, minuto)`, ou `None` quando não há horário.
    """
    match = _RE_TIME.search(text)
    if match:
        hour = int(match.group("h"))
        minute = match.group("m1") or match.group("m1b") or match.group("m2") or "0"
        if 0 <= hour <= 23 and 0 <= int(minute) <= 59:
            return hour, int(minute)
    match = _RE_TIME_AT.search(text)
    if match:
        hour = int(match.group("h"))
        if 0 <= hour <= 23:
            return hour, 0
    return None


def _remove(text: str, pattern: re.Pattern[str]) -> tuple[str, str | None]:
    """Separa um trecho do texto, devolvendo o resto e o trecho encontrado.

    Args:
        text: texto normalizado.
        pattern: padrão a procurar.

    Returns:
        Tupla com o texto restante e o trecho encontrado (`None` quando não há).
    """
    match = pattern.search(text)
    if not match:
        return text, None
    return text[: match.start()] + " " + text[match.end():], match.group(0)


def _match_relative_date(
    text: str, reference: datetime
) -> tuple[date | None, tuple[int, int] | None, str]:
    """Procura uma data relativa ou absoluta no texto.

    Args:
        text: texto normalizado.
        reference: instante de referência (agora, no fuso do usuário).

    Returns:
        Tupla com a data encontrada (`None` quando não há), o horário de parede
        que a expressão traz junto (`None` quando só há a data) e o texto restante.

    Observações:
        "daqui a duas horas" é um instante, não um dia: por isso a função também
        devolve o horário quando a distância é menor que um dia.
    """
    today = reference.date()
    remaining, found = _remove(text, _RE_TOMORROW)
    if found:
        return today + timedelta(days=2), None, remaining
    remaining, found = _remove(text, _RE_TODAY)
    if found:
        return today, None, remaining
    remaining, found = _remove(text, _RE_TOMORROW_1)
    if found:
        return today + timedelta(days=1), None, remaining

    remaining, found = _remove(text, _RE_IN)
    if found:
        match = _RE_IN.search(found)
        if match:
            seconds = _amount(match.group("n")) * _INTERVAL_UNITS.get(match.group("u"), 3600)
            if seconds < 86400:
                # Menos de um dia: o instante é exato (data **e** hora).
                target = reference + timedelta(seconds=seconds)
                return target.date(), (target.hour, target.minute), remaining
            return today + timedelta(seconds=seconds), None, remaining
        return today, None, remaining

    remaining, found = _remove(text, _RE_SLASH_DATE)
    if found:
        match = _RE_SLASH_DATE.search(found)
        if match:
            day = int(match.group(1))
            month = int(match.group(2))
            year = int(match.group(3)) if match.group(3) else today.year
            if year < 100:
                year += 2000
            try:
                return date(year, month, day), None, remaining
            except ValueError:
                return None, None, remaining
        return None, None, remaining

    remaining, found = _remove(text, _RE_DAY_MONTH)
    if found:
        match = _RE_DAY_MONTH.search(found)
        if match:
            month = _MONTH_NAMES.get(match.group(2))
            if month:
                try:
                    return date(today.year, month, int(match.group(1))), None, remaining
                except ValueError:
                    return None, None, remaining
        return None, None, remaining
    return None, None, text


def _match_next_weekday(
    text: str, today: date, current: date | None
) -> tuple[date | None, str]:
    """Reconhece "na próxima segunda": uma ocorrência, não uma recorrência.

    Args:
        text: texto normalizado.
        today: data de referência.
        current: data já reconhecida por outra regra (`None` quando não há).

    Returns:
        Tupla com a data reconhecida e o texto restante.
    """
    match = _RE_NEXT_WEEKDAY.search(text)
    if not match:
        return current, text
    before = text[: match.start()]
    if _RE_RECURRING.search(before):
        # "toda próxima segunda" continua recorrente: a regra da recorrência decide.
        return current, text
    name = _strip_accents(match.group(1))
    weekday = _WEEKDAY_NAMES.get(name)
    if weekday is None:
        if _RE_NEXT_WEEK.search(text):
            # "na próxima semana": sete dias à frente, como o usuário espera.
            remaining = text[: match.start()] + " " + text[match.end():]
            return today + timedelta(days=7), remaining
        return current, text
    remaining = text[: match.start()] + " " + text[match.end():]
    return _next_weekday(today, weekday), remaining


def _next_weekday(today: date, weekday: int) -> date:
    """Próxima data de um dia da semana (o próprio dia conta, quando é hoje).

    Args:
        today: data de referência.
        weekday: dia da semana alvo (0 = segunda).

    Returns:
        A data do próximo ocorrência.
    """
    ahead = (weekday - today.weekday()) % 7
    return today + timedelta(days=ahead or 7)


def _cron_dow(weekday: int) -> int:
    """Converte o dia da semana do Python (0 = segunda) para o do cron (0 = domingo).

    Args:
        weekday: dia da semana no calendário do Python.

    Returns:
        O número equivalente na expressão cron.
    """
    return (weekday + 1) % 7


def _format_local(moment: datetime, timezone: str) -> str:
    """Formata um instante no fuso local, para a prévia e para a resposta ao usuário.

    Args:
        moment: instante a formatar.
        timezone: fuso de exibição.

    Returns:
        Texto no formato `dd/mm/aaaa HH:MM`.
    """
    local = moment.astimezone(ZoneInfo(resolve_timezone(timezone)))
    return local.strftime("%d/%m/%Y %H:%M")


def _human_interval(seconds: int) -> str:
    """Duração em linguagem legível.

    Args:
        seconds: duração em segundos.

    Returns:
        Texto como `4 horas` ou `30 minutos`.
    """
    if seconds % 86400 == 0 and seconds >= 86400:
        days = seconds // 86400
        return f"{days} dia{'s' if days > 1 else ''}"
    if seconds % 3600 == 0 and seconds >= 3600:
        hours = seconds // 3600
        return f"{hours} hora{'s' if hours > 1 else ''}"
    if seconds % 60 == 0 and seconds >= 60:
        minutes = seconds // 60
        return f"{minutes} minuto{'s' if minutes > 1 else ''}"
    return f"{seconds} segundos"


def describe_cron(expression: str) -> str:
    """Descreve uma expressão cron em português, quando o padrão é reconhecível.

    Args:
        expression: expressão cron.

    Returns:
        Texto como «todos os dias às 09:00» ou a própria expressão, quando o
        padrão não é reconhecido.
    """
    parts = (expression or "").split()
    if len(parts) != 5:
        return expression or ""
    minute, hour, day, month, weekday = parts
    try:
        minute_value = int(minute)
        hour_value = int(hour)
    except ValueError:
        return expression
    clock = f"{hour_value:02d}:{minute_value:02d}"
    if day == "*" and month == "*":
        if weekday == "*":
            return f"todos os dias às {clock}"
        try:
            index = int(weekday)
        except ValueError:
            return expression
        names = ("domingo", "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado")
        return f"toda {names[index % 7]} às {clock}"
    if day == "L" and month == "*" and weekday == "*":
        return f"no último dia de cada mês às {clock}"
    if day.isdigit() and month == "*" and weekday == "*":
        return f"no dia {day} de cada mês às {clock}"
    return expression


def describe_trigger(trigger: TriggerSpec | None, *, timezone: str | None = None) -> str:
    """Descreve um gatilho em linguagem legível.

    Args:
        trigger: gatilho a descrever.
        timezone: fuso usado na exibição; quando ausente, usa o do gatilho.

    Returns:
        Uma frase curta com a recorrência e o fuso.
    """
    if trigger is None:
        return "(sem gatilho)"
    tz = timezone or trigger.timezone
    if trigger.kind is TriggerKind.ONCE and trigger.run_at is not None:
        return f"uma vez, em {_format_local(trigger.run_at, tz)} ({tz})"
    if trigger.kind is TriggerKind.INTERVAL:
        seconds = int(trigger.interval_seconds or 0)
        return f"a cada {_human_interval(seconds)} ({tz})"
    expression = (trigger.cron or "").strip()
    if expression:
        return f"{describe_cron(expression)} ({tz})"
    return f"gatilho {trigger.kind.value} ({tz})"


def parse_schedule(
    text: str,
    *,
    now: datetime | None = None,
    timezone: str | None = None,
) -> ScheduleIntent:
    """Interpreta um pedido de horário escrito em linguagem natural.

    Args:
        text: texto do usuário (por exemplo, "todos os dias às 9h").
        now: instante de referência; por padrão, a hora real do processo.
        timezone: fuso do usuário; quando ausente, usa `DEFAULT_TIMEZONE`.

    Returns:
        A intenção interpretada: gatilho pronto, pergunta de esclarecimento ou
        texto não reconhecido.

    Observações:
        A ordem de leitura é fixa: intervalo, data, recorrência, horário. Assim
        "a cada 4 horas" não vira "às 4h" e "amanhã às 14h" não vira "todos os
        dias às 14h".
    """
    tz = resolve_timezone(timezone or DEFAULT_TIMEZONE)
    reference = now.astimezone(ZoneInfo(tz)) if now else _now_in(tz)
    today = reference.date()
    raw = _strip_accents(text or "")
    if not raw.strip():
        return ScheduleIntent(
            kind="unparsed",
            question="Qual horário a automação deve ter? Diga algo como «amanhã às 14h» ou «todos os dias às 9h».",
        )

    # 1. Intervalo fixo — o mais específico, e o que não pode ser confundido com horário.
    interval_seconds = _match_interval(raw)
    if interval_seconds:
        anchor = reference.replace(second=0, microsecond=0)
        trigger = TriggerSpec(
            kind=TriggerKind.INTERVAL,
            interval_seconds=interval_seconds,
            run_at=anchor,
            timezone=tz,
        )
        return ScheduleIntent(
            kind="interval",
            trigger=trigger,
            summary=f"a cada {_human_interval(interval_seconds)}",
        )

    # 2. Data (relativa ou absoluta) — antes do horário, para não ler "às 9" de "às 9h30".
    day, exact_time, remaining = _match_relative_date(raw, reference)

    # 2b. "na próxima segunda" — uma ocorrência, não uma recorrência.
    day, remaining = _match_next_weekday(remaining, today, day)

    # 3. Recorrência.
    recurrence, remaining = _match_recurrence(remaining)

    # 4. Horário de parede.
    hour_minute = exact_time or _match_time(remaining) or _match_time(raw)

    if recurrence == "month_end":
        if hour_minute is None:
            return ScheduleIntent(
                kind="ambiguous",
                question="A que horas a automação deve rodar no último dia do mês?",
            )
        expression = f"{hour_minute[1]} {hour_minute[0]} L * *"
        trigger = TriggerSpec(kind=TriggerKind.CRON, cron=expression, timezone=tz)
        return ScheduleIntent(
            kind="cron",
            trigger=trigger,
            summary=f"no último dia de cada mês às {hour_minute[0]:02d}:{hour_minute[1]:02d}",
        )

    if recurrence in {"daily", "weekly", "hourly", "monthly", "weekday"}:
        if recurrence == "hourly" and hour_minute is None:
            trigger = TriggerSpec(kind=TriggerKind.CRON, cron="0 * * * *", timezone=tz)
            return ScheduleIntent(
                kind="cron", trigger=trigger, summary="de hora em hora, no início de cada hora"
            )
        if hour_minute is None:
            question = {
                "daily": "A que horas a automação deve rodar todos os dias?",
                "weekly": "Em que dia da semana e a que horas a automação deve rodar?",
                "monthly": "Em que dia do mês e a que horas a automação deve rodar?",
                "weekday": "A que horas a automação deve rodar?",
            }[recurrence]
            return ScheduleIntent(kind="ambiguous", question=question)
        if recurrence == "daily":
            expression = f"{hour_minute[1]} {hour_minute[0]} * * *"
            summary = f"todos os dias às {hour_minute[0]:02d}:{hour_minute[1]:02d}"
        elif recurrence == "hourly":
            expression = f"{hour_minute[1]} * * * *"
            summary = f"de hora em hora, aos {hour_minute[0]:02d}:{hour_minute[1]:02d}"
        elif recurrence == "monthly":
            day_of_month = _day_of_month(raw)
            if day_of_month is None:
                return ScheduleIntent(
                    kind="ambiguous",
                    question="Em que dia do mês a automação deve rodar?",
                )
            expression = f"{hour_minute[1]} {hour_minute[0]} {day_of_month} * *"
            summary = (
                f"no dia {day_of_month} de cada mês às {hour_minute[0]:02d}:{hour_minute[1]:02d}"
            )
        else:
            weekday = _weekday_from(raw)
            if weekday is None:
                return ScheduleIntent(
                    kind="ambiguous",
                    question="Em que dia da semana a automação deve rodar?",
                )
            expression = f"{hour_minute[1]} {hour_minute[0]} * * {_cron_dow(weekday)}"
            summary = (
                f"toda {_WEEKDAY_LABELS[weekday]} às {hour_minute[0]:02d}:{hour_minute[1]:02d}"
            )
        trigger = TriggerSpec(kind=TriggerKind.CRON, cron=expression, timezone=tz)
        return ScheduleIntent(kind="cron", trigger=trigger, summary=summary)

    # 5. Data + horário: execução única.
    if day is not None:
        if hour_minute is None:
            return ScheduleIntent(
                kind="ambiguous",
                question="A que horas a automação deve rodar nesse dia?",
            )
        naive = datetime.combine(day, datetime.min.time()).replace(
            hour=hour_minute[0], minute=hour_minute[1]
        )
        instant = localize(naive, tz)
        if instant <= reference:
            return ScheduleIntent(
                kind="ambiguous",
                question=(
                    f"O horário pedido ({naive.strftime('%d/%m/%Y %H:%M')}) já passou. "
                    "Repetir no dia seguinte ou escolher outra data?"
                ),
            )
        trigger = TriggerSpec(kind=TriggerKind.ONCE, run_at=instant, timezone=tz)
        return ScheduleIntent(
            kind="once",
            trigger=trigger,
            summary=f"uma vez, em {_format_local(instant, tz)}",
        )

    # 6. Só horário: hoje, se ainda vier; amanhã, se já tiver passado.
    if hour_minute is not None:
        naive = datetime.combine(today, datetime.min.time()).replace(
            hour=hour_minute[0], minute=hour_minute[1]
        )
        if naive <= reference.replace(tzinfo=None, second=0, microsecond=0):
            naive += timedelta(days=1)
        instant = localize(naive, tz)
        trigger = TriggerSpec(kind=TriggerKind.ONCE, run_at=instant, timezone=tz)
        return ScheduleIntent(
            kind="once",
            trigger=trigger,
            summary=f"uma vez, em {_format_local(instant, tz)}",
        )

    # 7. Só uma data relativa sem hora: falta o horário.
    if day is not None:
        return ScheduleIntent(
            kind="ambiguous",
            question="A que horas a automação deve rodar nesse dia?",
        )

    # 8. Texto impreciso demais: pergunta em vez de escolha.
    for marker in _VAGUE_MARKERS:
        if marker in raw:
            return ScheduleIntent(
                kind="ambiguous",
                question=(
                    "«"
                    + marker
                    + "» é impreciso para um agendamento. Qual horário exato devo usar?"
                ),
            )
    return ScheduleIntent(
        kind="unparsed",
        question=(
            "Não entendi o horário. Diga algo como «amanhã às 14h», «todos os dias às 9h», "
            "«toda segunda às 8h30» ou «a cada 4 horas»."
        ),
    )


def _match_interval(text: str) -> int | None:
    """Procura uma recorrência de intervalo fixo no texto.

    Args:
        text: texto normalizado.

    Returns:
        O intervalo em segundos, ou `None` quando não há.
    """
    match = _RE_INTERVAL.search(text)
    if match:
        amount = _amount(match.group("n"))
        return int(amount * _INTERVAL_UNITS.get(match.group("u"), 3600))
    match = _RE_EVERY.search(text)
    if match:
        amount = _amount(match.group("b"))
        return int(amount * _INTERVAL_UNITS.get(match.group("u"), 3600))
    if _RE_HOURLY.search(text):
        return 3600
    return None


def _match_recurrence(text: str) -> tuple[str | None, str]:
    """Reconhece a recorrência do texto.

    Args:
        text: texto normalizado.

    Returns:
        Tupla com a recorrência (`daily`, `weekly`, `hourly`, `monthly`, `weekday`,
        `month_end` ou `None`) e o texto restante.
    """
    remaining, found = _remove(text, _RE_MONTH_END)
    if found:
        return "month_end", remaining
    remaining, found = _remove(remaining, _RE_EVERY_DAY)
    if found:
        return "daily", remaining
    remaining, found = _remove(remaining, _RE_EVERY_HOUR)
    if found:
        return "hourly", remaining
    remaining, found = _remove(remaining, _RE_EVERY_WEEK)
    if found:
        return "weekly", remaining
    remaining, found = _remove(remaining, _RE_EVERY_MONTH)
    if found:
        return "monthly", remaining
    remaining, found = _remove(remaining, _RE_WEEKDAY)
    if found:
        return "weekday", remaining
    return None, remaining


def _day_of_month(text: str) -> int | None:
    """Dia do mês citado no texto ("dia 15", "15 de março").

    Args:
        text: texto normalizado.

    Returns:
        O dia do mês, ou `None` quando não há.
    """
    match = _RE_DAY_MONTH.search(text)
    if match and _MONTH_NAMES.get(match.group(2)):
        return int(match.group(1))
    match = _RE_DAY_OF_MONTH.search(text)
    if match:
        return int(match.group(1))
    return None


def _weekday_from(text: str) -> int | None:
    """Dia da semana citado no texto.

    Args:
        text: texto normalizado.

    Returns:
        O dia da semana (0 = segunda), ou `None` quando não há.
    """
    match = _RE_WEEKDAY.search(text)
    if not match:
        return None
    return _WEEKDAY_NAMES.get(match.group(1))


__all__ = [
    "DEFAULT_TIMEZONE",
    "ScheduleIntent",
    "describe_cron",
    "describe_trigger",
    "parse_schedule",
]
