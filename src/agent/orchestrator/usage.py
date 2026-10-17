# src/agent/orchestrator/usage.py — tokens gastos numa etapa


def accumulate_usage(metadata: dict | None, prompt: int, completion: int) -> dict:
    meta = dict(metadata or {})
    current = dict(meta.get("usage") or {})
    current["prompt"] = int(current.get("prompt") or 0) + int(prompt or 0)
    current["completion"] = int(current.get("completion") or 0) + int(completion or 0)
    current["total"] = current["prompt"] + current["completion"]
    meta["usage"] = current
    return meta


def remember_usage(provider, prompt: int | None, completion: int | None) -> None:
    prompt_count = int(prompt or 0)
    completion_count = int(completion or 0)
    if prompt_count or completion_count:
        provider.last_usage = (prompt_count, completion_count)
