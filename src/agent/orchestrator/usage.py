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
    """Guarda no provedor o consumo da última chamada, quando houve algum.

    Args:
        provider: provedor usado na chamada.
        prompt: tokens consumidos na entrada do modelo.
        completion: tokens consumidos na saída do modelo.

    Observações:
        Chamada sem consumo não sobrescreve o uso anterior do provedor.
    """
    prompt_count = int(prompt or 0)
    completion_count = int(completion or 0)
    if prompt_count or completion_count:
        provider.last_usage = (prompt_count, completion_count)
