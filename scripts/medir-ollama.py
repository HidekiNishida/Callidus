#!/usr/bin/env python3
"""scripts/medir-ollama.py — mede o comportamento real com um modelo local.

Roda um cenário de hierarquia de agentes contra o Ollama de verdade e mede o que
importa para a tese do projeto: **funciona bem com modelo pequeno e recursos
limitados**.

O que é medido:

| Métrica | Origem |
|---------|--------|
| Latência por inferência | relógio em volta de `provider.chat` |
| Número de chamadas ao modelo | métricas do executor compartilhado |
| Tamanho do contexto enviado | caracteres do prompt montado |
| Resposta correta / alucinação | o modelo foi perguntado sobre algo sem evidência |
| RAM do servidor de inferência | RSS dos processos `ollama` |
| Modelo carregado e VRAM | `GET /api/ps` do Ollama |

Uso:

    python scripts/medir-ollama.py [--model llama3.2:3b] [--json]

Não altera a configuração do Callidus: o modelo e a URL vêm de argumentos e do
ambiente, e nada é gravado no `.env`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agent.config import Settings  # noqa: E402
from agent.domain.schemas import ProjectCreate, TaskCreate  # noqa: E402
from agent.persistence.database import build_session_factory, init_db  # noqa: E402
from agent.providers.base import ModelProfile  # noqa: E402
from agent.providers.ollama import OllamaProvider  # noqa: E402
from agent.services.agent_service import AgentService  # noqa: E402
from agent.services.executor import get_executor, reset_executor  # noqa: E402
from agent.services.project_service import ProjectService  # noqa: E402
from agent.services.query_service import QueryService  # noqa: E402
from agent.services.task_service import TaskService  # noqa: E402


def rss_ollama_mb() -> float:
    """RSS total (MB) dos processos `ollama` — a memória que o servidor de inferência usa."""
    total = 0.0
    try:
        saida = subprocess.run(
            ["ps", "-o", "rss,command", "-ax"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except Exception:  # pragma: no cover - ambiente sem `ps`
        return 0.0
    for linha in saida.splitlines():
        if "ollama" not in linha.lower() or "grep" in linha:
            continue
        partes = linha.split(None, 1)
        if partes and partes[0].isdigit():
            total += int(partes[0]) / 1024
    return round(total, 1)


def modelo_carregado(base_url: str) -> dict:
    """`GET /api/ps` — modelo residente e VRAM, se o backend informar."""
    try:
        import httpx

        resposta = httpx.get(f"{base_url.rstrip('/')}/api/ps", timeout=10)
        dados = resposta.json()
    except Exception:  # pragma: no cover - servidor indisponível
        return {}
    modelos = dados.get("models") or []
    if not modelos:
        return {"carregado": False}
    primeiro = modelos[0]
    return {
        "carregado": True,
        "modelo": primeiro.get("name"),
        "tamanho_vram": primeiro.get("size_vram"),
        "tamanho": primeiro.get("size"),
        "atender": primeiro.get("expires_at"),
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.environ.get("DEFAULT_MODEL_ID", "llama3.2:3b"))
    parser.add_argument("--url", default=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    reset_executor()
    tmp = Path(tempfile.mkdtemp(prefix="callidus-ollama-"))
    try:
        settings = Settings(data_dir=tmp / "data")
        factory = build_session_factory(init_db(settings=settings))
        session = factory()
        project = ProjectService(session).create_project(
            ProjectCreate(name="ollama", root_path=str(tmp))
        )
        ts = TaskService(session)
        avo = ts.create_task(
            project.id, TaskCreate(title="Avô", objective="Investigar o incidente", kind="objective")
        )
        pai = ts.create_task(
            project.id,
            TaskCreate(title="Pai", objective="Coordenar", parent_id=avo.id, kind="subsystem"),
        )
        filho = ts.create_task(
            project.id,
            TaskCreate(title="Filho", objective="Ler o log", parent_id=pai.id, kind="operation"),
        )
        agents = AgentService(session)
        a_avo = agents.ensure_agent(avo.id)
        a_pai = agents.ensure_agent(pai.id)
        a_filho = agents.ensure_agent(filho.id)
        agents.record_finding(
            a_filho.id,
            "A causa da falha foi o import de math removido em calc.py",
            evidence=["calc.py:1"],
        )
        session.commit()

        provider = OllamaProvider(base_url=args.url, default_model=args.model)
        profile = ModelProfile(model_id=args.model)
        queries = QueryService(session)
        executor = get_executor(settings)

        rss_inicial = rss_ollama_mb()
        ps_inicial = modelo_carregado(args.url)

        # --- 1. consulta respondida pelo estado persistido (sem inferência) -----------
        inicio = time.monotonic()
        consulta = queries.ask(a_pai.id, a_filho.id, "qual foi a causa da falha?")
        respondida = await queries.resolve(consulta.id)
        latencia_estado = time.monotonic() - inicio
        inferencias_estado = executor.metrics().inferences_started

        # --- 2. consulta sem evidência: exige inferência real ------------------------
        contexto_caracteres = 0
        inicio = time.monotonic()
        consulta2 = queries.ask(a_pai.id, a_filho.id, "qual a probabilidade de reincidência?")
        respondida2 = await queries.resolve(consulta2.id, provider=provider, profile=profile)
        latencia_inferencia = time.monotonic() - inicio
        rss_durante = rss_ollama_mb()
        ps_durante = modelo_carregado(args.url)
        inferencias_total = executor.metrics().inferences_started

        # tamanho do contexto enviado: o prompt da consulta é o que o modelo recebe
        contexto_caracteres = len(queries._context_for(a_filho))

        # --- 3. suspender e retomar: o agente continua respondendo -------------------
        agents.start_execution(a_filho.id)
        agents.save_checkpoint(a_filho.id, {"step": "medindo"})
        agents.suspend(a_filho.id, reason="medição")
        consulta3 = queries.ask(a_pai.id, a_filho.id, "qual foi a causa da falha?")
        respondida3 = await queries.resolve(consulta3.id)
        latencia_pos_suspensao = time.monotonic() - inicio
        agents.resume(a_filho.id)

        rss_final = rss_ollama_mb()
        ps_final = modelo_carregado(args.url)

        payload2 = respondida2.answer_json or {}
        alucinou = bool(payload2.get("grounded")) is False and not payload2.get("uncertainty")
        resultado = {
            "modelo": args.model,
            "url": args.url,
            "latencia_consulta_sem_inferencia_sec": round(latencia_estado, 3),
            "latencia_consulta_com_inferencia_sec": round(latencia_inferencia, 3),
            "inferencias_da_consulta_com_estado": inferencias_estado,
            "inferencias_total": inferencias_total,
            "contexto_enviado_caracteres": contexto_caracteres,
            "resposta_sem_evidencia": (
                "sem evidência" in (respondida2.answer or "").lower()
            ),
            "fundamentada_no_estado": payload2.get("grounded"),
            "incertezas": payload2.get("uncertainty"),
            "modelo_alucinou": alucinou,
            "resposta_modelo": (respondida2.answer or "")[:300],
            "resposta_do_estado": (respondida.answer or "")[:200],
            "consulta_apos_suspensao": {
                "resposta": (respondida3.answer or "")[:200],
                "sem_inferencia": (respondida3.answer_json or {}).get("inference_used") is False,
            },
            "memoria": {
                "rss_ollama_inicio_mb": rss_inicial,
                "rss_ollama_durante_mb": rss_durante,
                "rss_ollama_final_mb": rss_final,
                "modelo_inicio": ps_inicial,
                "modelo_durante": ps_durante,
                "modelo_final": ps_final,
            },
            "executor": executor.metrics().snapshot(),
        }
        session.close()

        if args.json:
            print(json.dumps(resultado, indent=2, ensure_ascii=False))
        else:
            print("Medição com Ollama real")
            print("-" * 64)
            print(f"modelo .................... {resultado['modelo']}")
            print(
                f"consulta respondida do estado {resultado['latencia_consulta_sem_inferencia_sec']:.3f} s "
                f"({resultado['inferencias_da_consulta_com_estado']} inferências)"
            )
            print(
                f"consulta com inferência ..... {resultado['latencia_consulta_com_inferencia_sec']:.3f} s "
                f"({resultado['inferencias_total']} inferências no total)"
            )
            print(f"contexto enviado ............ {resultado['contexto_enviado_caracteres']} caracteres")
            print(f"resposta sem evidência ..... {resultado['resposta_sem_evidencia']}")
            print(f"modelo alucinou ............ {resultado['modelo_alucinou']}")
            print(f"RSS ollama ................. {rss_inicial} MB → {rss_durante} MB → {rss_final} MB")
            print(f"modelo carregado ........... {resultado['memoria']['modelo_final']}")
            print(f"concorrência máxima ........ {resultado['executor']['max_active']}")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        reset_executor()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
