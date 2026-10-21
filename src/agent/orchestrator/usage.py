"""
Arquivo: src/agent/orchestrator/usage.py
Nome: usage.py
Propósito: tokens gastos numa etapa.
Responsabilidade: camada de aplicação.
Componentes: accumulate_usage, remember_usage.
Dependências: .
Observações: o estado canônico é o SQLite; a verificação é independente de quem executa.
"""



def accumulate_usage(metadata: dict | None, prompt: int, completion: int) -> dict:
    """Soma o consumo de tokens de uma chamada ao uso já registrado da etapa.

    Args:
        metadata: metadados da etapa, onde o uso é acumulado.
        prompt: tokens consumidos na entrada do modelo.
        completion: tokens consumidos na saída do modelo.

    Returns:
        Os metadados com o uso atualizado, com o total recalculado.

    Observações:
        A função não altera o dicionário recebido: devolve uma cópia.
    """
    meta = dict(metadata or {})
    current = dict(meta.get("usage") or {})
    current["prompt"] = int(current.get("prompt") or 0) + int(prompt or 0)
    current["completion"] = int(current.get("completion") or 0) + int(completion or 0)
    current["total"] = current["prompt"] + current["completion"]
    meta["usage"] = current
    return meta


def remember_usage(provider, prompt: int | None, completion: int | None) -> None:
    """Acrescenta o consumo desta chamada ao diário do provedor.

    Args:
        provider: provedor usado na chamada.
        prompt: tokens de entrada informados, ou `None` quando o provedor não os mandou.
        completion: tokens de saída informados, ou `None` quando o provedor não os mandou.

    Observações:
        Cada chamada entra na lista. A última não apaga as anteriores. Ausência
        continua `None`; só um zero informado pelo provedor vira zero.
        `last_usage` guarda o par mais recente que teve algum número, para os
        chamadores que ainda leem só a última resposta.
    """
    prompt_count = None if prompt is None else int(prompt)
    completion_count = None if completion is None else int(completion)
    log = list(getattr(provider, "usage_log", None) or [])
    log.append({"prompt": prompt_count, "completion": completion_count})
    provider.usage_log = log
    if prompt_count or completion_count:
        provider.last_usage = (int(prompt_count or 0), int(completion_count or 0))
