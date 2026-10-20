#!/usr/bin/env python3
"""
Arquivo: scripts/avaliar-consultas.py
Nome: avaliar-consultas.py
Propósito: avaliar, com gabarito, a qualidade do casamento lexical das consultas sob demanda.
Responsabilidade: camada de script — mede acertos, falsos positivos e falsos negativos do casamento entre pergunta e estado persistido.
Componentes: gabarito de quatro classes de pergunta, montagem do estado persistido, execução das consultas e relatório por classe.
Dependências: agent.services (query_service, agent_service, project_service, task_service), agent.persistence.database, agent.config.Settings.
Observações: trabalha em banco temporário próprio, não usa rede nem credencial e não altera dados do usuário.


qualidade do casamento lexical das consultas.

Mede, com gabarito, o quanto o Callidus acerta ao responder uma pergunta a partir do
estado persistido de um agente. O gabarito tem quatro classes de pergunta:

| Classe | O que espera |
|--------|--------------|
| `direta` | A pergunta repete os termos da descoberta — deve acertar |
| `indireta` | A pergunta usa sinônimos — pode acertar ou cair na inferência |
| `ambigua` | A pergunta é vaga — o sistema **não deve** inventar resposta |
| `sem_evidencia` | A resposta não existe no estado — o sistema **deve** dizer que não sabe |

O critério de sucesso não é só acertar: é **não afirmar o que não sabe**. Uma resposta
errada com confiança é pior do que uma resposta que admite a ausência de evidência.

Uso:

    python scripts/avaliar-consultas.py [--json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agent.config import Settings  # noqa: E402
from agent.domain.schemas import ProjectCreate, TaskCreate  # noqa: E402
from agent.persistence.database import build_session_factory, init_db  # noqa: E402
from agent.services.agent_service import AgentService  # noqa: E402
from agent.services.project_service import ProjectService  # noqa: E402
from agent.services.query_service import QueryService  # noqa: E402
from agent.services.task_service import TaskService  # noqa: E402

#: Descobertas persistidas no agente (o "conhecimento" disponível).
DESCOBERTAS = [
    (
        "A causa da falha foi o import de math removido em calc.py",
        ["calc.py:1", "log: linha 42"],
    ),
    (
        "Os testes executados foram pytest -q e 3 testes passaram",
        ["pytest: 3 passed"],
    ),
    (
        "A configuracao do servidor usa a porta 8765 e o host 127.0.0.1",
        ["config.py:12"],
    ),
    (
        "O deploy foi feito no ambiente de homologacao em 12/10/2026",
        ["deploy.log: linha 8"],
    ),
]

#: (classe, pergunta, gabarito). O gabarito `None` significa "não há resposta".
GABARITO = [
    ("direta", "qual foi a causa da falha?", 0),
    ("direta", "quais testes foram executados?", 1),
    ("direta", "em que porta o servidor escuta?", 2),
    ("indireta", "o que o deploy encontrou de diferente?", 3),
    ("indireta", "qual arquivo estava com problema?", 0),
    ("indireta", "onde foi o deploy?", 3),
    ("ambigua", "falhou?", None),
    ("ambigua", "como esta isso?", None),
    ("sem_evidencia", "qual o nome do responsavel tecnico?", None),
    ("sem_evidencia", "quando o contrato expira?", None),
    ("sem_evidencia", "quantos usuarios ativos existem?", None),
    # adversarial:oglyph estas não podem casar com nada do estado
    ("sem_evidencia", "quando acontece a proxima reuniao?", None),
    ("sem_evidencia", "qual framework de testes foi adotado?", None),
    ("sem_evidencia", "quantas replicas de producao existem?", None),
    ("sem_evidencia", "qual o orcamento aprovado para o trimestre?", None),
]


def montar_estado(tmp: Path):
    """Cria o projeto, a árvore de tarefas e os agentes, e persiste as descobertas usadas no gabarito."""
    settings = Settings(data_dir=tmp / "data")
    factory = build_session_factory(init_db(settings=settings))
    session = factory()
    project = ProjectService(session).create_project(
        ProjectCreate(name="avaliacao", root_path=str(tmp))
    )
    ts = TaskService(session)
    raiz = ts.create_task(
        project.id, TaskCreate(title="Raiz", objective="Investigar incidente", kind="objective")
    )
    filho = ts.create_task(
        project.id,
        TaskCreate(title="Filho", objective="Coletar evidências", parent_id=raiz.id, kind="operation"),
    )
    agents = AgentService(session)
    agente_pai = agents.ensure_agent(raiz.id)
    agente = agents.ensure_agent(filho.id)
    for texto, evidencia in DESCOBERTAS:
        agents.record_finding(agente.id, texto, evidence=evidencia)
    session.commit()
    return session, agente, agente_pai


async def main() -> int:
    """Executa o gabarito contra o serviço de consultas e imprime o relatório de acertos."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="saída em JSON")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="callidus-avaliar-"))
    session, agente, agente_pai = montar_estado(tmp)
    queries = QueryService(session)

    linhas = []
    for classe, pergunta, esperado in GABARITO:
        consulta = queries.ask(agente_pai.id, agente.id, pergunta)
        respondida = await queries.resolve(consulta.id)
        payload = respondida.answer_json or {}
        encontrado = queries.answer_from_persisted(consulta)
        if esperado is None:
            # Para o gabarito "sem evidência", acertar é NÃO afirmar uma descoberta.
            acertou = encontrado is None
            achou = None
        else:
            achou = (
                DESCOBERTAS.index(
                    (
                        next(
                            (
                                d["text"]
                                for d in AgentService(session).findings(agente.id)
                                if d["text"] == DESCOBERTAS[esperado][0]
                            ),
                            "",
                        ),
                        DESCOBERTAS[esperado][1],
                    )
                )
                if encontrado is not None
                else None
            )
            acertou = achou == esperado
        linhas.append(
            {
                "classe": classe,
                "pergunta": pergunta,
                "esperado": esperado,
                "achou": achou,
                "acertou": acertou,
                "respondeu_sem_inferencia": payload.get("inference_used") is False,
                "texto_resposta": (respondida.answer or "")[:70],
            }
        )

    por_classe: dict[str, dict[str, int]] = {}
    for linha in linhas:
        bucket = por_classe.setdefault(linha["classe"], {"total": 0, "acertos": 0})
        bucket["total"] += 1
        bucket["acertos"] += 1 if linha["acertou"] else 0
    acertos = sum(1 for linha in linhas if linha["acertou"])
    falsos_positivos = sum(
        1
        for linha in linhas
        if linha["esperado"] is None and not linha["acertou"]
    )
    falsos_negativos = sum(
        1
        for linha in linhas
        if linha["esperado"] is not None and not linha["acertou"]
    )

    resultado = {
        "total": len(linhas),
        "acertos": acertos,
        "taxa_acerto": round(acertos / len(linhas), 4),
        "falsos_positivos": falsos_positivos,
        "falsos_negativos": falsos_negativos,
        "por_classe": por_classe,
        "detalhe": linhas,
    }
    session.close()

    if args.json:
        print(json.dumps(resultado, indent=2, ensure_ascii=False))
    else:
        print("Qualidade das consultas lexicais")
        print("-" * 72)
        for linha in linhas:
            marca = "ok  " if linha["acertou"] else "FALHA"
            esperado = (
                "sem evidência"
                if linha["esperado"] is None
                else f"descoberta #{linha['esperado']}"
            )
            print(f"{marca} [{linha['classe']:<13}] {linha['pergunta']}")
            print(f"       esperado={esperado:<18} achou={linha['achou']}")
        print("-" * 72)
        print(f"acerto ................. {acertos}/{len(linhas)} ({resultado['taxa_acerto'] * 100:.1f}%)")
        print(f"falsos positivos ...... {falsos_positivos}")
        print(f"falsos negativos ...... {falsos_negativos}")
        for classe, bucket in por_classe.items():
            print(f"  {classe:<14} {bucket['acertos']}/{bucket['total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
