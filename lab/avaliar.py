"""Avaliação reproduzível do Callidus com o modelo local de referência.

Executa um conjunto de cenários com o Ollama local (`gpt-oss:20b` por padrão) num banco e
numa pasta de trabalho **isolados** — nada do banco, dos projetos ou das credenciais do
usuário é tocado. Cada cenário tem critérios de aceite objetivos, e o resultado é medido
(tarefas, chamadas, tokens, evidências, requisitos comprovados).

Uso:
    python lab/avaliar.py --label depois            # mede o estado atual
    python lab/avaliar.py --label antes --checkout HEAD   # mede o estado de um commit

Saída: `lab/out/avaliacao-<label>.json` e um resumo no terminal.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import select

from agent.config import Settings
from agent.domain.enums import TaskKind, TaskStatus
from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
from agent.orchestrator.global_verify import requirements_report
from agent.orchestrator.runner import RunOrchestrator
from agent.persistence.database import build_session_factory, init_db
from agent.persistence.models import EventLogModel, EvidenceModel, OperationAttemptModel, TaskModel
from agent.services.project_service import ProjectService
from agent.services.run_service import RunService
from agent.services.task_service import TaskService

OUT = Path(__file__).resolve().parent / "out"
# Pasta de trabalho dos cenários. `AVALIACAO_WORKDIR` permite rodar duas avaliações em
# paralelo (antes e depois) sem que uma apague o banco e a pasta da outra.
WORK = Path(os.environ.get("AVALIACAO_WORKDIR", "/tmp/callidus-avaliacao"))


# ────────────────────────────────────────────────────────────────────── cenários


def _cenario_funcional(ws: Path) -> dict:
    """Uma função com critério de aceite objetivo: o arquivo passa a existir e o teste passa."""
    (ws / "app.py").write_text("def hello():\n    return 'oi'\n", encoding="utf-8")
    (ws / "test_app.py").write_text(
        "import app\n\n\ndef test_dobro():\n    assert app.dobro(3) == 6\n", encoding="utf-8"
    )
    return {
        "name": "funcional",
        "objective": "Crie em app.py uma função dobro(x) que retorna x vezes 2.",
        "accept": {
            "dobro devolve o dobro": lambda: _call(ws, "app.py", "dobro", 3) == 6,
            "teste passa": lambda: _pytest_passes(ws),
        },
    }


def _cenario_bug(ws: Path) -> dict:
    """Causa raiz: a função está errada e o teste reprova. O agente precisa achar e corrigir."""
    (ws / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (ws / "test_calc.py").write_text(
        "import calc\n\n\ndef test_add():\n    assert calc.add(2, 3) == 5\n", encoding="utf-8"
    )
    return {
        "name": "bug",
        "objective": "O teste test_calc.py está falhando. Descubra a causa e corrija o módulo do projeto para que add(a, b) retorne a soma.",
        "accept": {
            # Comportamento, não texto: `int(a) + int(b)` também soma.
            "add soma de verdade": lambda: _call_add(ws) == 5,
            "teste passa": lambda: _pytest_passes(ws),
            "teste não foi adulterado": lambda: "assert calc.add(2, 3) == 5"
            in (ws / "test_calc.py").read_text(encoding="utf-8"),
        },
    }


def _call_add(ws: Path):
    """Chama `add` do módulo do projeto e devolve o resultado."""
    return _call(ws, "calc.py", "add", 2, 3)


def _call(ws: Path, module_name: str, func: str, *args):
    """Chama uma função do módulo do projeto e devolve o resultado (ou `None`)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"alvo_{module_name[:-3]}", ws / module_name)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return getattr(module, func)(*args)
    except Exception:
        return None


def _cenario_multirequisito(ws: Path) -> dict:
    """Dois requisitos: os dois precisam ser comprovados, não só um."""
    (ws / "a.py").write_text("# vazio\n", encoding="utf-8")
    (ws / "b.py").write_text("# vazio\n", encoding="utf-8")
    return {
        "name": "multirequisito",
        "objective": "Pedido:\n- em a.py, crie a função soma(a, b) que retorna a mais b\n- em b.py, crie a função sub(a, b) que retorna a menos b",
        "accept": {
            "soma soma de verdade": lambda: _call(ws, "a.py", "soma", 1, 2) == 3,
            "sub subtrai de verdade": lambda: _call(ws, "b.py", "sub", 3, 1) == 2,
        },
    }


def _cenario_verificacao_reprova(ws: Path) -> dict:
    """Verificação que tem de reprovar: a suíte do projeto está quebrada e o pedido é **só
    rodar e reportar**, sem tocar em nenhum arquivo.

    Critérios: nada foi alterado, e a resposta final **diz** que o teste reprovou. Uma
    resposta que afirma sucesso em silêncio seria uma conclusão falsa.
    """
    (ws / "app.py").write_text("def hello():\n    return 'oi'\n", encoding="utf-8")
    original_test = "import app\n\n\ndef test_soma():\n    assert app.soma(1, 2) == 4\n"
    (ws / "test_app.py").write_text(original_test, encoding="utf-8")
    original_app = (ws / "app.py").read_text(encoding="utf-8")
    return {
        "name": "verificacao_reprova",
        "objective": "Execute a suíte de testes do projeto e diga o resultado. Não altere nenhum arquivo do projeto.",
        "accept": {
            "app.py inalterado": lambda: (ws / "app.py").read_text(encoding="utf-8") == original_app,
            "teste inalterado": lambda: (ws / "test_app.py").read_text(encoding="utf-8") == original_test,
        },
    }


def _cenario_pergunta_simples(ws: Path) -> dict:
    """Pergunta simples: não deve gerar árvore de subtarefas."""
    return {
        "name": "pergunta_simples",
        "objective": "Qual é a capital do Brasil?",
        "accept": {"sem arquivos criados": lambda: not any(ws.iterdir())},
    }


def _pytest_passes(ws: Path) -> bool:
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(ws)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.returncode == 0


SCENARIOS = [
    _cenario_funcional,
    _cenario_bug,
    _cenario_multirequisito,
    _cenario_verificacao_reprova,
    _cenario_pergunta_simples,
]


# ────────────────────────────────────────────────────────────────────── execução


class _Failing:
    """Provedor que reproduz uma falha observada em produção, de forma determinística.

    Atributos:
        mode: qual falha reproduzir.
        calls: quantas chamadas já respondeu.
    """

    name = "fault"
    last_usage = None

    def __init__(self, mode: str) -> None:
        """Guarda o modo de falha e zera o contador de chamadas."""
        self.mode = mode
        self.calls = 0

    async def chat(self, request):
        """Devolve a falha programada ou a entrega válida, conforme o modo.

        Args:
            request: pedido do orquestrador (ignorado).

        Returns:
            A resposta falsa.

        Raises:
            ProviderError: nos modos `http400` e `transitorio` (na primeira chamada).
        """
        from agent.providers.base import ProviderError

        self.calls += 1
        if self.mode == "http400":
            raise ProviderError("openrouter: requisição recusada (HTTP 400).")
        if self.mode == "transitorio" and self.calls == 1:
            raise ProviderError("ollama indisponível: connection refused")
        if self.mode == "vazio":
            content = ""
        elif self.mode == "invalido":
            content = "Vou escrever o arquivo agora, com o conteúdo pedido."
        else:
            content = '{"path":"app.py","content":"def dobro(x):\\n    return x * 2\\n"}'

        class _R:
            """Resposta falsa com o conteúdo programado."""

        _R.content = content
        return _R()


async def run_scenario(
    scenario_fn,
    *,
    model_id: str,
    provider: str,
    max_steps: int,
    fault: str = "",
) -> dict:
    label = scenario_fn.__name__.replace("_cenario_", "")
    ws = WORK / label
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    db = WORK / f"{label}.db"
    if db.exists():
        db.unlink()

    settings = Settings(data_dir=Path("data"), database_url=f"sqlite:///{db}")
    engine = init_db(settings=settings)
    session = build_session_factory(engine)()

    scenario = scenario_fn(ws)
    project = ProjectService(session).create_project(
        ProjectCreate(name=f"avaliacao {label}", root_path=str(ws))
    )
    root = TaskService(session).create_task(
        project.id,
        TaskCreate(
            title=label,
            objective=scenario["objective"],
            kind=TaskKind.OBJECTIVE,
            metadata={"locale": "pt"},
        ),
    )
    run = RunService(session).start_run(
        project.id,
        ExecutionRunCreate(
            root_task_id=root.id,
            config={
                "provider": provider,
                "model_id": model_id,
                "approve_risky_tools": True,
                "browser_mode": "off",
            },
        ),
    )
    session.commit()

    if fault:
        import agent.orchestrator.runner as runner_module

        runner_module._select_provider = lambda _s, _c: _Failing(fault)

    started = time.monotonic()
    orchestrator = RunOrchestrator(session, settings)
    actions: list[str] = []
    for _ in range(max_steps):
        out = await orchestrator.step(run.id)
        session.commit()
        actions.append(str(out.get("action")))
        if out.get("action") in {
            "run_completed",
            "run_terminal",
            "run_paused",
            "run_stalled",
            "run_failed",
        }:
            break
    elapsed = time.monotonic() - started

    tasks = list(session.scalars(select(TaskModel)).all())
    attempts = list(session.scalars(select(OperationAttemptModel)).all())
    evidences = list(session.scalars(select(EvidenceModel)).all())
    reqs = requirements_report(session, root)
    events = list(session.scalars(select(EventLogModel)).all())
    event_types = [e.event_type for e in events]

    prompt_tokens = 0
    completion_tokens = 0
    for task in tasks:
        usage = (task.metadata_json or {}).get("usage") or {}
        prompt_tokens += int(usage.get("prompt") or 0)
        completion_tokens += int(usage.get("completion") or 0)

    accept = {name: bool(check()) for name, check in scenario["accept"].items()}
    if label == "verificacao_reprova":
        # Critério real: a resposta final tem de dizer que o teste reprovou.
        answer = str((root.consolidated_result_json or {}).get("final_answer") or "")
        accept["a resposta final reporta a reprovação"] = bool(
            any(
                termo in answer.lower()
                for termo in ("reprov", "falhou", "falha", "erro", "não passou", "nao passou")
            )
        )

    proved = [r for r in reqs if r["status"] == "satisfied"]
    unmet = [r for r in reqs if r["status"] not in {"satisfied", "não_aplicável", "informativo"}]
    premature = run.status == "completed" and bool(unmet)
    finished = run.status in {"completed", "failed", "cancelled", "paused"}

    report = {
        "cenario": label,
        "segundos": round(elapsed, 1),
        "passos": len(actions),
        "acoes": actions,
        "run_status": run.status,
        "run_terminou": finished,
        "conclusao_prematura": premature,
        "tarefas": len(tasks),
        "profundidade": _depth(tasks),
        "model_calls": sum(1 for a in attempts if a.kind == "model"),
        "tool_calls": sum(1 for a in attempts if a.kind == "tool"),
        "falhas_modelo": sum(1 for a in attempts if a.kind == "model" and not a.success),
        "estagnacoes": event_types.count("run.stagnation"),
        "replanejamentos": event_types.count("task.replanned"),
        "pausas": event_types.count("run.paused"),
        "problemas": {
            key: {"count": value.get("count"), "total": value.get("total")}
            for key, value in ((root.metadata_json or {}).get("problem_ledger") or {}).items()
        },
        "evidencias": len(evidences),
        "evidencias_aprovadas": sum(1 for e in evidences if e.passed is True),
        "evidencias_reprovadas": sum(1 for e in evidences if e.passed is False),
        "requisitos": len(reqs),
        "requisitos_comprovados": len(proved),
        "requisitos_nao_comprovados": [r["id"] for r in unmet],
        "tokens_prompt": prompt_tokens,
        "tokens_completion": completion_tokens,
        "aceite": accept,
        "aceite_ok": all(accept.values()),
        "estado_tarefas": {t.title: t.status for t in tasks},
    }
    session.close()
    return report


def _depth(tasks) -> int:
    by_id = {t.id: t for t in tasks}
    best = 0
    for task in tasks:
        depth = 0
        current = task
        seen = set()
        while current.parent_id and current.parent_id not in seen:
            seen.add(current.parent_id)
            parent = by_id.get(current.parent_id)
            if parent is None:
                break
            current = parent
            depth += 1
        best = max(best, depth)
    return best


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="atual")
    parser.add_argument("--model", default="gpt-oss:20b")
    parser.add_argument("--provider", default="meu_ollama")
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--only", default="")
    parser.add_argument(
        "--fault",
        default="",
        help=(
            "injeta uma falha determinística no provedor (`vazio`, `http400`, `invalido`, "
            "`transitorio`) para medir a resposta do sistema à repetição improdutiva"
        ),
    )
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    reports = []
    for scenario_fn in SCENARIOS:
        if args.only and args.only not in scenario_fn.__name__:
            continue
        print(f"→ {scenario_fn.__name__} ...", flush=True)
        report = await run_scenario(
            scenario_fn,
            model_id=args.model,
            provider=args.provider,
            max_steps=args.max_steps,
            fault=args.fault,
        )
        reports.append(report)
        print(
            f"   run={report['run_status']} aceite={report['aceite_ok']} "
            f"tarefas={report['tarefas']} reqs={report['requisitos_comprovados']}/{report['requisitos']} "
            f"model_calls={report['model_calls']} estagn={report['estagnacoes']} "
            f"replan={report['replanejamentos']} {report['segundos']}s",
            flush=True,
        )

    summary = {
        "label": args.label,
        "modelo": args.model,
        "falha_injetada": args.fault,
        "cenarios": len(reports),
        "aceite_total": sum(1 for r in reports if r["aceite_ok"]),
        "runs_completos": sum(1 for r in reports if r["run_status"] == "completed"),
        "runs_terminados": sum(1 for r in reports if r["run_terminou"]),
        "conclusoes_prematuras": sum(1 for r in reports if r["conclusao_prematura"]),
        "requisitos_comprovados": sum(r["requisitos_comprovados"] for r in reports),
        "requisitos_total": sum(r["requisitos"] for r in reports),
        "tarefas": sum(r["tarefas"] for r in reports),
        "model_calls": sum(r["model_calls"] for r in reports),
        "falhas_modelo": sum(r["falhas_modelo"] for r in reports),
        "estagnacoes": sum(r["estagnacoes"] for r in reports),
        "replanejamentos": sum(r["replanejamentos"] for r in reports),
        "pausas": sum(r["pausas"] for r in reports),
        "tokens_completion": sum(r["tokens_completion"] for r in reports),
        "segundos": round(sum(r["segundos"] for r in reports), 1),
    }
    (OUT / f"avaliacao-{args.label}.json").write_text(
        json.dumps({"resumo": summary, "cenarios": reports}, ensure_ascii=False, indent=1)
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
