#!/usr/bin/env python3
"""scripts/medir-hierarquia.py — mede o ganho das consultas sob demanda.

Compara, **no mesmo cenário**, duas maneiras de o pai obter a informação do filho:

| Caminho | Como o pai obtém | Inferências | Caracteres levados ao pai |
|---------|-------------------|-------------|---------------------------|
| `relatorio` | lê o relatório consolidado inteiro do filho | 0 | tamanho do relatório completo |
| `consulta` | pergunta ao filho pelo identificador | 0 ou 1 | tamanho da resposta |

O cenário é o mesmo dos dois lados: mesma árvore, mesmo estado persistido, mesmo
provedor (mock). A diferença é **apenas** como o pai pede a informação.

Uso:

    python scripts/medir-hierarquia.py [--niveis 3] [--json]

O script é reprodutível: não usa rede, não usa credencial e não altera dados do
usuário (trabalha em um banco temporário).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agent.config import Settings  # noqa: E402
from agent.domain.schemas import ProjectCreate, TaskCreate  # noqa: E402
from agent.persistence.database import build_session_factory, init_db  # noqa: E402
from agent.persistence.models import TaskModel  # noqa: E402
from agent.services.agent_service import AgentService  # noqa: E402
from agent.services.project_service import ProjectService  # noqa: E402
from agent.services.query_service import QueryService  # noqa: E402
from agent.services.task_service import TaskService  # noqa: E402
from agent.services.executor import get_executor, reset_executor  # noqa: E402


def montar_cenario(tmp: Path, niveis: int):
    """Árvore de `niveis` gerações, cada uma com uma descoberta persistida."""
    settings = Settings(data_dir=tmp / "data")
    factory = build_session_factory(init_db(settings=settings))
    session = factory()
    project = ProjectService(session).create_project(
        ProjectCreate(name="medicao", root_path=str(tmp))
    )
    ts = TaskService(session)
    parent = ts.create_task(
        project.id, TaskCreate(title="Avô", objective="Resolver o incidente", kind="objective")
    )
    agents = AgentService(session)
    agente_pai = agents.ensure_agent(parent.id)
    agente = agente_pai
    for nivel in range(1, niveis):
        filho = ts.create_task(
            project.id,
            TaskCreate(
                title=f"Nível {nivel}",
                objective=f"Investigar nível {nivel}",
                parent_id=parent.id,
                kind="subsystem" if nivel < niveis - 1 else "operation",
            ),
        )
        agente = agents.ensure_agent(filho.id)
        parent = filho
    # O descendente mais profundo guarda a evidência.
    agents.record_finding(
        agente.id,
        "A causa da falha foi o import de math removido em calc.py "
        "(detalhes, métricas, histórico completo do processo e contexto de depuração "
        "que não interessam ao pai)",
        evidence=["calc.py:1", "log: linha 42"],
    )
    # O pai recebe o relatório consolidado: o mecanismo que existia antes.
    filho_task = ts.get_task(agente.task_id)
    filho_task.consolidated_result_json = {
        "children": [
            {
                "task_id": str(agente.task_id),
                "title": "Nível final",
                "evidence_ok": True,
                "result": {
                    "summary": agents.findings(agente.id)[0]["text"],
                    "details": "x" * 2000,
                },
            }
        ],
        "evidences": [{"verifier": "pytest", "passed": True, "summary": "3 passed"}],
    }
    session.commit()
    return session, agente, agente_pai


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--niveis", type=int, default=3, help="profundidade da hierarquia")
    parser.add_argument("--json", action="store_true", help="saída em JSON")
    args = parser.parse_args()

    reset_executor()
    tmp = Path(tempfile.mkdtemp(prefix="callidus-medir-"))
    try:
        session, agente_fundo, agente_pai = montar_cenario(tmp, args.niveis)
        executor = get_executor()
        queries = QueryService(session)

        # Caminho 1 — relatório completo: o pai recebe o resultado consolidado inteiro
        # do filho (é o que o mecanismo anterior entregava a cada delegação).
        filho_task = session.get(TaskModel, agente_fundo.task_id)
        relatorio = filho_task.consolidated_result_json or {}
        tamanho_relatorio = len(json.dumps(relatorio, default=str))

        # Caminho 2 — consulta dirigida ao filho.
        antes = executor.metrics().inferences_started
        consulta = queries.ask(agente_pai.id, agente_fundo.id, "qual foi a causa da falha?")
        respondida = await queries.resolve(consulta.id)
        depois = executor.metrics().inferences_started
        tamanho_resposta = len(respondida.answer or "")

        resultado = {
            "niveis": args.niveis,
            "caminho_relatorio": {
                "caracteres_levados_ao_pai": tamanho_relatorio,
                "inferencias": 0,
                "inclui_historico": True,
            },
            "caminho_consulta": {
                "caracteres_levados_ao_pai": tamanho_resposta,
                "inferencias": depois - antes,
                "respondida_sem_inferencia": depois == antes,
                "quem_respondeu": str(respondida.answered_by_agent_id),
                "alvo": str(agente_fundo.id),
            },
            "executor": {
                "limite": executor.limit,
                "max_concorrencia_observada": executor.metrics().max_active,
            },
        }
        resultado["reducao_de_contexto"] = (
            round(1 - tamanho_resposta / tamanho_relatorio, 4) if tamanho_relatorio else None
        )

        # Caminho 3 — pergunta sem evidência: o filho é reativado e a inferência passa
        # pelo executor compartilhado. Serve para medir a exclusividade de verdade.
        from agent.providers.base import ModelProfile  # noqa: E402
        from agent.providers.mock import MockProvider  # noqa: E402

        provider = MockProvider(responses=["Resposta do modelo"])
        consulta2 = queries.ask(
            agente_pai.id, agente_fundo.id, "qual a probabilidade de reincidência?"
        )
        await queries.resolve(
            consulta2.id, provider=provider, profile=ModelProfile(model_id="mock")
        )
        resultado["consulta_sem_evidencia"] = {
            "inferencias": executor.metrics().inferences_started - antes,
            "max_concorrencia_observada": executor.metrics().max_active,
            "limite": executor.limit,
        }

        session.close()
        if args.json:
            print(json.dumps(resultado, indent=2, ensure_ascii=False))
        else:
            print("Medição das consultas sob demanda")
            print("-" * 52)
            print(f"niveis da hierarquia ............ {resultado['niveis']}")
            print(
                f"relatório completo .............. {tamanho_relatorio:>6} caracteres, "
                f"0 inferências"
            )
            print(
                f"consulta dirigida ............... {tamanho_resposta:>6} caracteres, "
                f"{resultado['caminho_consulta']['inferencias']} inferências"
            )
            print(
                "redução de contexto ............. "
                f"{resultado['reducao_de_contexto'] * 100:.1f}%"
                if resultado["reducao_de_contexto"] is not None
                else "redução de contexto ............. n/d"
            )
            sem_evidencia = resultado["consulta_sem_evidencia"]
            print(
                "consulta sem evidência .......... "
                f"{sem_evidencia['inferencias']} inferência, concorrência máxima "
                f"{sem_evidencia['max_concorrencia_observada']} "
                f"(limite {sem_evidencia['limite']})"
            )
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        reset_executor()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
