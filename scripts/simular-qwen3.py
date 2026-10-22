#!/usr/bin/env python3
"""
Arquivo: scripts/simular-qwen3.py
Nome: simular-qwen3.py
Propósito: medir, sem modelo real, como o Callidus se comporta diante das propriedades do servidor Ollama servindo o qwen3:8b.
Responsabilidade: script de medição — roda cenários de ponta a ponta (planejar → alterar → verificar → responder) contra um servidor Ollama simulado e relata chamadas, tokens, cortes de janela e desfecho.
Componentes: ServidorSimulado, CENARIOS, rodar_cenario, main.
Dependências: agent.orchestrator.runner, agent.providers.ollama, agent.services, httpx (transporte simulado), tests/fixtures/sample_project.
Observações: mede a **resposta do sistema** às propriedades do servidor, não a qualidade do qwen3:8b. Nada do banco ou dos projetos do usuário é tocado: banco e pasta são temporários.

O que o servidor simulado reproduz (comportamento documentado do Ollama, não inventado):

| Propriedade | Simulação |
|-------------|-----------|
| Janela padrão sem `num_ctx` | 4 096 tokens (padrão do Ollama em máquinas com menos de 24 GiB de VRAM) |
| Prompt maior que a janela | as mensagens mais antigas depois do sistema saem primeiro; se ainda não couber, o começo do texto é cortado — sem aviso na resposta |
| Ferramentas | os esquemas entram no prompt (o template do qwen3 os renderiza) |
| Contagem de tokens | 3 caracteres por token |

O "modelo" do simulador é determinístico e só **vê** o que sobrou depois do corte: se a instrução
de formato ou o objetivo sumiram, ele responde em prosa (o que um modelo pequeno faz sem a
instrução). Com tudo visível, entrega certo. Assim, a diferença entre antes e depois mede só o
que o Callidus manda ao servidor.

Uso:

    python scripts/simular-qwen3.py            # todos os cenários
    python scripts/simular-qwen3.py --json     # saída em JSON

Para comparar com outro commit, rode o mesmo script num *worktree* desse commit.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import httpx  # noqa: E402

FIXED = 'def add(a: int, b: int) -> int:\n    """Soma dois inteiros."""\n    return a + b\n'
PLAN = {
    "subtasks": [
        {"title": "Ler calc.py", "objective": "Ler calc.py", "metadata": {"tool": "read_file", "tool_args": {"path": "calc.py"}}},
        {
            "title": "Corrigir a soma",
            "objective": "Corrigir a função add em calc.py para somar",
            "metadata": {"model_operation": True, "atomic": True},
            "depends_on_indices": [0],
        },
        {
            "title": "Rodar os testes",
            "objective": "Rodar a suíte",
            "metadata": {"verification": {"type": "pytest", "path": "tests"}},
            "depends_on_indices": [1],
        },
        {
            "title": "Responder",
            "objective": "Resumir o que foi feito",
            "metadata": {"final_answer": True, "model_operation": True},
            "depends_on_indices": [2],
        },
    ]
}


@dataclass
class ServidorSimulado:
    """Servidor Ollama falso com as propriedades de janela do Ollama real e um modelo determinístico.

    Atributos:
        janela_padrao: janela usada quando o corpo não traz `num_ctx`.
        leituras_extras: quantos arquivos o modelo lê antes de alterar (simula inspeção longa).
        pensamento_no_texto: o modelo escreve `<think></think>` no conteúdo (servidor sem canal de raciocínio).
    """

    janela_padrao: int = 4096
    leituras_extras: int = 0
    pensamento_no_texto: bool = False
    chamadas: int = 0
    cortes: int = 0
    tokens_enviados: int = 0
    tokens_vistos: int = 0
    janelas: set = field(default_factory=set)

    @staticmethod
    def _tokens(text: str) -> int:
        """Contagem do simulador: 3 caracteres por token."""
        return -(-len(text) // 3)

    def _visivel(self, body: dict) -> str:
        """O que o modelo realmente lê depois do corte da janela (mesma ordem do Ollama)."""
        options = body.get("options") or {}
        janela = int(options.get("num_ctx") or self.janela_padrao)
        saida = int(options.get("num_predict") or 0)
        limite = max(256, janela - max(saida, 0))
        self.janelas.add(janela)
        ferramentas = json.dumps(body.get("tools") or [], ensure_ascii=False)
        mensagens = [dict(m) for m in body.get("messages") or []]

        def total(items: list[dict]) -> int:
            """Tokens das mensagens mais as ferramentas renderizadas no template."""
            return self._tokens(ferramentas) + sum(self._tokens(str(m.get("content") or "")) for m in items)

        enviado = total(mensagens)
        self.tokens_enviados += enviado
        cortou = False
        # 1) mensagens antigas (depois do sistema) saem até sobrar a última.
        while total(mensagens) > limite:
            removiveis = [i for i, m in enumerate(mensagens[:-1]) if m.get("role") != "system"]
            if not removiveis:
                break
            mensagens.pop(removiveis[0])
            cortou = True
        texto = "\n".join(str(m.get("content") or "") for m in mensagens)
        # 2) ainda não coube: o começo do texto se perde.
        excesso = total(mensagens) - limite
        if excesso > 0:
            texto = texto[excesso * 3 :]
            cortou = True
        if cortou:
            self.cortes += 1
        self.tokens_vistos += min(enviado, limite)
        return texto

    def _resposta(self, body: dict) -> dict:
        """Resposta do modelo determinístico para o que ficou visível."""
        self.chamadas += 1
        visivel = self._visivel(body)
        prefixo = "<think>\n\n</think>\n\n" if self.pensamento_no_texto else ""
        mensagem: dict = {"role": "assistant", "content": ""}
        tools = {((t.get("function") or {}).get("name")) for t in body.get("tools") or []}
        if body.get("format") is not None or "Responda SOMENTE JSON válido" in visivel:
            mensagem["content"] = prefixo + json.dumps(PLAN)
        elif "Decomponha TODAS as etapas" in visivel:
            mensagem["content"] = prefixo + "Vou ler o arquivo e corrigir a soma."
        elif "Resumir o que foi feito" in visivel:
            mensagem["content"] = prefixo + "## Resultado\n\n- `calc.py` agora soma; a suíte passa.\n"
        elif "Corrigir a função add" in visivel and "write_file" in visivel:
            lidos = visivel.count("[resultado read_file]")
            if "read_file" in tools and lidos <= self.leituras_extras:
                alvo = "calc.py" if lidos == 0 else f"docs/nota{lidos}.md"
                mensagem["tool_calls"] = [{"function": {"name": "read_file", "arguments": {"path": alvo}}}]
            else:
                mensagem["content"] = prefixo + json.dumps({"path": "calc.py", "content": FIXED})
        else:
            # Sem objetivo ou sem a instrução de formato visível: um modelo pequeno responde prosa.
            mensagem["content"] = prefixo + "Certo, posso ajudar com isso."
        return {
            "model": body.get("model"),
            "message": mensagem,
            "done": True,
            "done_reason": "stop",
            "prompt_eval_count": self._tokens(visivel),
            "eval_count": self._tokens(mensagem.get("content") or "") + 5,
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        """Transporte HTTP simulado do `/api/chat` (com e sem streaming)."""
        body = json.loads(request.content)
        for message in body.get("messages") or []:
            if message.get("role") == "tool":
                message["content"] = "[resultado read_file]\n" + str(message.get("content") or "")
        data = self._resposta(body)
        if body.get("stream"):
            return httpx.Response(200, content=(json.dumps(data) + "\n").encode("utf-8"))
        return httpx.Response(200, json=data)


CENARIOS = {
    "simples": {"descricao": "corrigir a soma de calc.py e rodar os testes", "servidor": {}},
    "inspecao_longa": {
        "descricao": "mesma correção, mas o modelo lê 6 arquivos grandes antes de alterar",
        "servidor": {"leituras_extras": 6},
        "arquivos_grandes": 6,
    },
    "arquivo_realista": {
        "descricao": "mesma correção num calc.py de ~9 KB (tamanho comum num projeto real) e 2 leituras de apoio",
        "servidor": {"leituras_extras": 2},
        "arquivos_grandes": 2,
        "calc_grande": True,
    },
    "realista_inspecao_longa": {
        "descricao": "calc.py de ~9 KB e 6 leituras de apoio antes de alterar (a conversa do ciclo cresce)",
        "servidor": {"leituras_extras": 6},
        "arquivos_grandes": 6,
        "calc_grande": True,
    },
    "pensamento_no_texto": {
        "descricao": "o servidor não separa o raciocínio: `<think></think>` chega no conteúdo",
        "servidor": {"pensamento_no_texto": True},
    },
}


async def rodar_cenario(nome: str, spec: dict, max_steps: int = 60) -> dict:
    """Roda um cenário de ponta a ponta com o servidor simulado e devolve as métricas.

    Args:
        nome: nome do cenário.
        spec: definição do cenário (`servidor`, `arquivos_grandes`).
        max_steps: orçamento de passos do orquestrador.

    Returns:
        Métricas do cenário (desfecho, chamadas, cortes de janela, tokens).
    """
    from agent.config import Settings
    from agent.domain.schemas import ExecutionRunCreate, ProjectCreate, TaskCreate
    from agent.orchestrator import runner as runner_module
    from agent.orchestrator.runner import RunOrchestrator
    from agent.persistence.database import build_session_factory, init_db
    from agent.persistence.models import ExecutionRunModel, TaskModel
    from agent.providers import ollama as ollama_module
    from agent.providers.ollama import OllamaProvider
    from agent.services.project_service import ProjectService
    from agent.services.run_service import RunService
    from agent.services.task_service import TaskService

    servidor = ServidorSimulado(**spec.get("servidor", {}))
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(servidor.handler)

    def factory(*args, **kwargs):
        """Cliente HTTP do adaptador apontado para o servidor simulado."""
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        workspace = tmp_path / "workspace"
        shutil.copytree(ROOT / "tests" / "fixtures" / "sample_project", workspace)
        (workspace / "docs").mkdir()
        if spec.get("calc_grande"):
            extra = "".join(
                f"\n\ndef operacao_{i}(valores: list[int]) -> int:\n"
                f'    """Operação auxiliar {i}: acumula os valores com o fator {i}."""\n'
                f"    total = 0\n    for valor in valores:\n        total += valor * {i}\n    return total\n"
                for i in range(1, 46)
            )
            calc = workspace / "calc.py"
            calc.write_text(calc.read_text() + extra)
        for index in range(1, int(spec.get("arquivos_grandes", 0)) + 1):
            (workspace / "docs" / f"nota{index}.md").write_text(f"# Nota {index}\n" + ("texto de apoio. " * 400))
        settings = Settings(data_dir=tmp_path / "data", enable_background_worker=False)
        session = build_session_factory(init_db(settings=settings))()
        project = ProjectService(session).create_project(ProjectCreate(name="sim", root_path=str(workspace)))
        root = TaskService(session).create_task(
            project.id,
            TaskCreate(title="Pedido", objective="Corrija a função add em calc.py para somar e rode os testes."),
        )
        run = RunService(session).start_run(
            project.id,
            ExecutionRunCreate(root_task_id=root.id, config={"provider": "ollama", "model_id": "qwen3:8b"}),
        )
        session.commit()
        provider = OllamaProvider("http://127.0.0.1:11434", default_model="qwen3:8b")
        original_select = runner_module._select_provider
        original_client = ollama_module.httpx.AsyncClient
        runner_module._select_provider = lambda settings, config: provider
        ollama_module.httpx.AsyncClient = factory
        try:
            log = await RunOrchestrator(session, settings).run_until_idle(run.id, max_steps=max_steps)
        finally:
            runner_module._select_provider = original_select
            ollama_module.httpx.AsyncClient = original_client
        session.commit()
        status = session.get(ExecutionRunModel, run.id).status
        # Texto que o Callidus guardou como resultado (resposta final incluída).
        answer = " ".join(
            json.dumps(t.consolidated_result_json or {}, ensure_ascii=False)
            for t in session.query(TaskModel).filter(TaskModel.project_id == project.id).all()
        )
        fixed = "a + b" in (workspace / "calc.py").read_text()
        return {
            "cenario": nome,
            "descricao": spec["descricao"],
            "status_run": status,
            "calc_corrigido": fixed,
            "passos": len(log),
            "chamadas_modelo": servidor.chamadas,
            "chamadas_com_corte": servidor.cortes,
            "tokens_enviados": servidor.tokens_enviados,
            "tokens_vistos": servidor.tokens_vistos,
            "janelas_pedidas": sorted(servidor.janelas),
            "pensamento_na_resposta": "<think>" in answer,
        }


def main() -> int:
    """Roda os cenários e imprime o resumo.

    Returns:
        0 sempre (a medição relata; não é portão de qualidade).
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", help="saída em JSON")
    parser.add_argument("--only", default="", help="roda só o cenário com este nome")
    parser.add_argument(
        "--janela-padrao",
        type=int,
        default=4096,
        help="janela do servidor quando o corpo não traz num_ctx (4096 abaixo de 24 GiB de VRAM; 32768 de 24 a 48 GiB)",
    )
    args = parser.parse_args()
    resultados = []
    for nome, spec in CENARIOS.items():
        if args.only and args.only != nome:
            continue
        spec = {**spec, "servidor": {**spec.get("servidor", {}), "janela_padrao": args.janela_padrao}}
        resultados.append(asyncio.run(rodar_cenario(nome, spec)))
    if args.json:
        print(json.dumps(resultados, ensure_ascii=False, indent=2))
        return 0
    for item in resultados:
        print(
            f"{item['cenario']:<20} run={item['status_run']:<10} corrigido={item['calc_corrigido']!s:<5} "
            f"chamadas={item['chamadas_modelo']:<3} com_corte={item['chamadas_com_corte']:<3} "
            f"tokens_enviados={item['tokens_enviados']:<6} janelas={item['janelas_pedidas']} "
            f"think_na_resposta={item['pensamento_na_resposta']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
