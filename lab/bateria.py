"""
Arquivo: lab/bateria.py
Nome: bateria.py
Propósito: verificar o Callidus numa bateria de dez cenários práticos (programação, interface,
    pesquisa, IAs externas, bug, arquitetura, desempenho, API, automação e problema composto).
Responsabilidade: laboratório — prepara cada cenário numa pasta e num banco isolados, roda o
    run com limite de tempo, mede o aceite por critérios objetivos e pontua seis dimensões.
Componentes: CENARIOS (dez preparadores), pontuar, main; reaproveita `run_scenario` de `lab/avaliar.py`.
Dependências: lab/avaliar.py, playwright (cenários visuais), sqlite3, subprocess.
Observações: o aceite é medido de fora — arquivos, testes do agente rodados por nós, sondas
    escondidas, navegador real — e nunca pelo relatório do próprio Callidus. A pontuação é uma
    fórmula fixa sobre essas medidas (documentada em docs/architecture/bateria.md); nada de nota
    por intenção. O histórico é só acrescentado (`lab/out/bateria/historico.jsonl`).

Uso:
    python lab/bateria.py --label inicial                      # os dez cenários
    python lab/bateria.py --label t05 --only desconto          # um cenário
    python lab/bateria.py --label x --model qwen3-vl:8b        # outro modelo
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import avaliar  # noqa: E402  (o laboratório não é pacote; o caminho acima o torna importável)

OUT = Path(__file__).resolve().parent / "out" / "bateria"
WORK = Path(os.environ.get("BATERIA_WORKDIR", "/tmp/callidus-bateria"))
TIME_LIMIT = 600.0

# Dimensões da pontuação, na ordem do relatório.
DIMENSOES = ("compreensao", "planejamento", "ferramentas", "autonomia", "execucao", "verificacao")


# ────────────────────────────────────────────────────────────────────── utilitários de aceite


# Desligado em `--reavaliar`: os critérios são reaplicados sobre o que o agente deixou no disco,
# sem regravar os arquivos de partida do cenário.
_SETUP = {"on": True}


def _w(ws: Path, rel: str, text: str) -> str:
    """Grava um arquivo de partida do cenário, criando as pastas, e devolve o texto gravado."""
    body = textwrap.dedent(text).lstrip("\n")
    if _SETUP["on"]:
        path = ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return body


def _wb(ws: Path, rel: str, data: bytes) -> None:
    """Grava um arquivo binário de partida do cenário."""
    if _SETUP["on"]:
        path = ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _read(ws: Path, rel: str) -> str:
    """Conteúdo do arquivo, ou texto vazio quando não existe."""
    path = ws / rel
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _pytest(ws: Path, *targets: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Roda o pytest na pasta do cenário, sem cache e sem plugins do usuário."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *targets],
        cwd=str(cwd or ws),
        capture_output=True,
        text=True,
        timeout=240,
    )


def _passes(ws: Path, *targets: str) -> bool:
    """`True` quando o pytest passa e coleta pelo menos um teste."""
    proc = _pytest(ws, *targets)
    return proc.returncode == 0 and " passed" in proc.stdout


def _count_tests(ws: Path) -> int:
    """Quantos testes o pytest coleta na pasta."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", "-p", "no:cacheprovider"],
        cwd=str(ws), capture_output=True, text=True, timeout=120,
    )
    match = re.search(r"(\d+) tests? collected", proc.stdout) or re.search(r"(\d+) tests?", proc.stdout)
    return int(match.group(1)) if match else 0


def _probe(ws: Path, code: str, timeout: int = 120) -> tuple[bool, str]:
    """Roda uma sonda Python na pasta do cenário (fora do processo do agente)."""
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=str(ws), capture_output=True, text=True, timeout=timeout,
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-600:]


def _ok(ws: Path, code: str, timeout: int = 120) -> bool:
    """`True` quando a sonda termina sem erro."""
    return _probe(ws, code, timeout)[0]


def _urls(text: str) -> list[str]:
    """URLs http(s) citadas no texto, sem pontuação final."""
    return [u.rstrip(").,;]>'\"") for u in re.findall(r"https?://[^\s)\]>'\"]+", text or "")]


def _domain(url: str) -> str:
    """Domínio da URL, sem `www.`."""
    host = re.sub(r"^https?://", "", url).split("/")[0].lower()
    return host[4:] if host.startswith("www.") else host


def _tool_text(ctx: dict) -> str:
    """Tudo o que as ferramentas devolveram no run (para conferir se uma fonte foi lida)."""
    return ctx.get("tool_text", "")


def _cited_sources_were_read(ctx: dict, text: str, minimum: int) -> bool:
    """Ao menos `minimum` domínios distintos citados no texto apareceram numa resposta de ferramenta.

    Fonte citada e nunca devolvida por uma ferramenta é fonte inventada — não conta.
    """
    seen = _tool_text(ctx).lower()
    domains = {_domain(u) for u in _urls(text) if _domain(u) and _domain(u) in seen}
    return len(domains) >= minimum


def _cited_error_pages(ctx: dict, text: str) -> list[str]:
    """URLs citadas no texto que, quando abertas pelo agente, responderam erro (404, 403, …)."""
    bad = []
    for url in _urls(text):
        for blob in ctx.get("browser_results", []):
            if blob.get("url", "").rstrip("/") == url.rstrip("/") and (
                (isinstance(blob.get("status"), int) and blob["status"] >= 400)
                or re.match(r"\s*(404|403|not found|page not found)\b", str(blob.get("title") or ""), re.I)
            ):
                bad.append(url)
    return bad


def _browser_page(url: str, width: int, height: int = 900, script: str = "") -> dict:
    """Abre a página num Chromium real e devolve DOM, console e medidas."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url, wait_until="load", timeout=120000)
        page.wait_for_timeout(1500)
        data = page.evaluate(
            script
            or """() => ({
                overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
            })"""
        )
        browser.close()
    data["console_errors"] = errors
    return data


# ────────────────────────────────────────────────────────────────────── cenários


def _cenario_t01_text_analyzer(ws: Path) -> dict:
    """T01 — programação e testes: um módulo com contrato definido e testes escritos pelo agente."""
    objective = (
        "Crie o módulo Python text_analyzer.py com estas funções:\n"
        "- count_words(text) -> int: número de palavras (sequências separadas por espaço em branco)\n"
        "- count_chars(text) -> int: número de caracteres, incluindo espaços\n"
        "- count_lines(text) -> int: número de linhas (texto vazio tem 0 linhas)\n"
        "- most_common_words(text, n=3) -> list[tuple[str, int]]: as n palavras mais frequentes, "
        "sem diferenciar maiúsculas, ignorando pontuação (ex.: 'Olá!' conta como 'olá'), "
        "em ordem decrescente de frequência e, no empate, alfabética\n"
        "Contrato de erro: se text não for str, todas levantam TypeError; se n < 1, most_common_words levanta ValueError.\n"
        "Crie test_text_analyzer.py com pytest cobrindo casos normais, texto vazio, caracteres especiais "
        "(acentos, pontuação, emoji) e entradas inválidas. Execute os testes e informe o resultado."
    )

    def hidden() -> bool:
        return _ok(ws, """
            import text_analyzer as t
            assert t.count_words('') == 0 and t.count_lines('') == 0 and t.count_chars('') == 0
            assert t.count_words('a b  c\\n d') == 4
            assert t.count_chars('ab c') == 4
            assert t.count_lines('a\\nb\\nc') == 3
            assert t.most_common_words('Olá! olá, mundo. Mundo mundo zz', 2) == [('mundo', 3), ('olá', 2)]
            assert t.most_common_words('b a', 2) == [('a', 1), ('b', 1)]
            for f in (t.count_words, t.count_chars, t.count_lines, t.most_common_words):
                try:
                    f(None)
                except TypeError:
                    pass
                else:
                    raise SystemExit(f'{f.__name__} aceitou None')
            try:
                t.most_common_words('a', 0)
            except ValueError:
                pass
            else:
                raise SystemExit('n=0 aceito')
        """)

    tests = lambda: _read(ws, "test_text_analyzer.py")  # noqa: E731
    return {
        "name": "t01_text_analyzer",
        "titulo": "Programação e testes",
        "objective": objective,
        "tools_required": ["write_file|edit_file", "run_pytest|run_command|run_check"],
        "checks": {
            "compreensao": {
                "text_analyzer.py criado": lambda: (ws / "text_analyzer.py").exists(),
                "testes do agente criados": lambda: (ws / "test_text_analyzer.py").exists(),
            },
            "execucao": {
                "contrato atendido (sonda escondida)": hidden,
            },
            "verificacao": {
                "testes do agente passam": lambda: _passes(ws, "test_text_analyzer.py"),
                "≥ 6 testes": lambda: _count_tests(ws) >= 6,
                "testam vazio e inválido": lambda: ("''" in tests() or '""' in tests())
                and "raises" in tests(),
                "resposta cita o resultado dos testes": lambda ctx=None: True,
            },
        },
        "answer_checks": {
            "verificacao": {"resposta cita o resultado dos testes": r"\d+ passed|\d+ testes? (?:passa|aprovad)|testes? (?:passaram|passou|aprovados)"},
        },
    }


_DASH_SCRIPT = """() => {
  const q = (s) => document.querySelectorAll(s);
  const chart = document.querySelector('[data-testid="chart"]');
  let chartDrawn = false;
  if (chart) {
    const c = chart.tagName === 'CANVAS' ? chart : chart.querySelector('canvas');
    const svg = chart.tagName === 'svg' ? chart : chart.querySelector('svg');
    if (c) {
      const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
      for (let i = 3; i < d.length; i += 4) { if (d[i] !== 0) { chartDrawn = true; break; } }
    }
    if (svg) chartDrawn = chartDrawn || svg.querySelectorAll('rect,path,circle,line,polyline').length >= 3;
  }
  const visible = (el) => !!el && el.getBoundingClientRect().width > 0 && getComputedStyle(el).display !== 'none';
  return {
    sidebar: visible(document.querySelector('[data-testid="sidebar"]')),
    main: visible(document.querySelector('[data-testid="main"]')),
    kpis: q('[data-testid="kpi"]').length,
    chartDrawn,
    tasks: q('[data-testid="task-list"] li').length,
    hasEmpty: !!document.querySelector('[data-testid="empty-state"]'),
    hasLoading: !!document.querySelector('[data-testid="loading"]'),
    overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
  };
}"""


def _cenario_t02_dashboard(ws: Path) -> dict:
    """T02 — interface visual: dashboard estático verificado num navegador real."""
    objective = (
        "Crie um dashboard web estático em index.html (com style.css e app.js na mesma pasta, "
        "sem bibliotecas externas nem CDN) contendo:\n"
        '- menu lateral com data-testid="sidebar" e área principal com data-testid="main"\n'
        '- pelo menos 3 indicadores de desempenho, cada um com data-testid="kpi"\n'
        '- um gráfico de barras desenhado em <canvas> ou <svg> com data-testid="chart"\n'
        '- uma lista de tarefas <ul data-testid="task-list"> com itens <li> vindos de dados em app.js\n'
        '- um estado de carregamento (data-testid="loading") e um estado sem dados (data-testid="empty-state")\n'
        "- layout responsivo: em 375 px de largura não pode haver rolagem horizontal\n"
        "Abra a página no navegador, confira que não há erros no console e capture uma screenshot."
    )

    def page(width: int) -> dict:
        index = ws / "index.html"
        if not index.exists():
            return {}
        try:
            return _browser_page(index.as_uri(), width, script=_DASH_SCRIPT)
        except Exception as exc:  # o aceite registra a falha, não derruba a bateria
            return {"erro": str(exc)[:200]}

    cache: dict[int, dict] = {}

    def at(width: int) -> dict:
        if width not in cache:
            cache[width] = page(width)
        return cache[width]

    return {
        "name": "t02_dashboard",
        "titulo": "Interface visual",
        "objective": objective,
        "browser_mode": "headless",
        "tools_required": ["write_file|edit_file", "browser"],
        "checks": {
            "compreensao": {
                "index.html criado": lambda: (ws / "index.html").exists(),
                "sem CDN": lambda: "http" not in re.sub(r"xmlns=\"[^\"]+\"", "", _read(ws, "index.html")),
            },
            "execucao": {
                "menu e área principal visíveis": lambda: bool(at(1280).get("sidebar") and at(1280).get("main")),
                "≥ 3 indicadores": lambda: at(1280).get("kpis", 0) >= 3,
                "gráfico desenhado": lambda: bool(at(1280).get("chartDrawn")),
                "tarefas renderizadas": lambda: at(1280).get("tasks", 0) >= 1,
                "estados de carregamento e vazio": lambda: bool(at(1280).get("hasEmpty") and at(1280).get("hasLoading")),
                "sem rolagem horizontal em 375 px": lambda: at(375) != {} and not at(375).get("overflow", True),
            },
            "verificacao": {
                "console sem erros": lambda: at(1280) != {} and not at(1280).get("console_errors"),
                "agente abriu a página no navegador": lambda ctx=None: True,
                "agente capturou screenshot": lambda ctx=None: True,
            },
        },
        "ctx_checks": {
            "verificacao": {
                "agente abriu a página no navegador": lambda ctx: "index.html" in ctx["browser_urls"],
                "agente capturou screenshot": lambda ctx: ctx["screenshots"] > 0,
            },
        },
    }


def _cenario_t03_pesquisa_vue(ws: Path) -> dict:
    """T03 — pesquisa externa: três fontes independentes, lidas de verdade, e uma recomendação."""
    objective = (
        "Pesquise na web por que gráficos em aplicações Vue 3 podem não atualizar mesmo quando os dados "
        "parecem estar sendo alterados. Consulte pelo menos três fontes independentes (priorize a "
        "documentação oficial do Vue e de bibliotecas de gráficos). Escreva relatorio.md com: as causas "
        "possíveis, as soluções (separadas das causas), a recomendação técnica, as limitações e a lista "
        "de referências com a URL de cada fonte que você leu. Não cite fonte que não abriu."
    )
    rel = lambda: _read(ws, "relatorio.md")  # noqa: E731
    return {
        "name": "t03_pesquisa_vue",
        "titulo": "Pesquisa externa",
        "objective": objective,
        "browser_mode": "headless",
        "tools_required": ["browser|http_request"],
        "checks": {
            "compreensao": {
                "relatorio.md criado": lambda: len(rel()) > 400,
                "fala de reatividade": lambda: bool(re.search(r"reativ|reactiv", rel(), re.I)),
            },
            "execucao": {
                "≥ 3 domínios citados": lambda: len({_domain(u) for u in _urls(rel())}) >= 3,
                "causa técnica concreta": lambda: bool(
                    re.search(r"shallowRef|markRaw|toRaw|reactive\(|ref\(|proxy|deep|watch|update\(\)", rel(), re.I)
                ),
                "causas e soluções separadas": lambda: bool(re.search(r"causa", rel(), re.I))
                and bool(re.search(r"solu", rel(), re.I)),
                "recomendação": lambda: bool(re.search(r"recomend", rel(), re.I)),
                # `Vue.set`/`this.$set` são do Vue 2; recomendá-los no Vue 3 é erro técnico.
                "sem API do Vue 2 recomendada como solução": lambda: not re.search(r"Vue\.set|\$set\(", rel()),
            },
            "verificacao": {
                "≥ 3 fontes citadas foram realmente lidas": lambda ctx=None: True,
                "nenhuma fonte citada é página de erro": lambda ctx=None: True,
                "limitações explicitadas": lambda: bool(re.search(r"limita", rel(), re.I)),
            },
        },
        "ctx_checks": {
            "verificacao": {
                "≥ 3 fontes citadas foram realmente lidas": lambda ctx: _cited_sources_were_read(ctx, rel(), 3),
                "nenhuma fonte citada é página de erro": lambda ctx: not _cited_error_pages(ctx, rel()),
            },
        },
    }


def _cenario_t04_ias_externas(ws: Path) -> dict:
    """T04 — IAs externas: consultar de verdade ou declarar o bloqueio, nunca simular."""
    objective = (
        "Investigue: \"Uma aplicação FastAPI apresenta aumento progressivo de latência após permanecer em "
        "execução por várias horas. Quais são as causas prováveis e como investigá-las?\" Tente consultar "
        "pelo menos duas IAs externas pelo navegador (por exemplo ChatGPT em https://chatgpt.com e Gemini em "
        "https://gemini.google.com), recupere as respostas reais, compare-as, verifique as afirmações "
        "principais em fontes técnicas e escreva consulta_ias.md com: a pergunta enviada, a resposta de cada "
        "IA com a origem, concordâncias, divergências, o que foi verificado em fonte técnica (com URL) e a "
        "recomendação. Se um serviço exigir login, CAPTCHA ou intervenção humana, registre o bloqueio e "
        "siga com as demais fontes. Nunca afirme ter consultado uma IA que você não consultou."
    )
    rel = lambda: _read(ws, "consulta_ias.md")  # noqa: E731

    def honest(ctx: dict) -> bool:
        """Sem resposta de IA capturada por ferramenta, o relatório tem de declarar o bloqueio."""
        consulted = ctx["ai_answers_captured"] > 0
        text = rel().lower()
        declares_block = bool(re.search(r"bloque|login|captcha|não foi possível|nao foi possivel|indispon|autentica", text))
        return consulted or declares_block

    return {
        "name": "t04_ias_externas",
        "titulo": "Consulta a IAs externas",
        "objective": objective,
        "browser_mode": "headless",
        "tools_required": ["browser"],
        "checks": {
            "compreensao": {
                "consulta_ias.md criado": lambda: len(rel()) > 300,
                "pergunta registrada": lambda: "fastapi" in rel().lower(),
            },
            "execucao": {
                "≥ 2 IAs consultadas de verdade": lambda ctx=None: True,
                "causas técnicas listadas": lambda: bool(
                    re.search(r"vazamento|leak|pool|conex|memória|memory|event loop|bloque", rel(), re.I)
                ),
            },
            "verificacao": {
                "não afirma consulta inexistente": lambda ctx=None: True,
                "≥ 1 fonte técnica lida": lambda ctx=None: True,
            },
        },
        "ctx_checks": {
            "execucao": {"≥ 2 IAs consultadas de verdade": lambda ctx: ctx["ai_answers_captured"] >= 2},
            "verificacao": {
                "não afirma consulta inexistente": honest,
                "≥ 1 fonte técnica lida": lambda ctx: _cited_sources_were_read(ctx, rel(), 1),
            },
        },
        "blocked_if": lambda ctx: ctx["ai_answers_captured"] == 0 and ctx["ai_pages_opened"] > 0,
    }


_PRICING = '''
"""Cálculo do desconto progressivo de um pedido."""


def desconto_percentual(total):
    """Percentual de desconto pela faixa do total: 0, 10 (>= 100) ou 20 (>= 500)."""
    if total < 0:
        raise ValueError("total negativo")
    if total >= 100:
        return 10
    elif total >= 500:
        return 20
    return 0


def total_com_desconto(total):
    """Total depois do desconto, com duas casas."""
    return round(total * (100 - desconto_percentual(total)) / 100, 2)
'''


def _cenario_t05_desconto(ws: Path) -> dict:
    """T05 — bug de causa raiz: a faixa de 20 % nunca é alcançada (ordem das condições)."""
    _w(ws, "pricing.py", _PRICING)
    original_tests = _w(ws, "test_pricing.py", """
        import pricing


        def test_faixa_dez():
            assert pricing.total_com_desconto(150) == 135.0


        def test_sem_desconto():
            assert pricing.total_com_desconto(50) == 50.0
    """)
    _w(ws, "RELATO.md", """
        Cliente reclamou: um pedido de R$ 600,00 saiu por R$ 540,00, mas a regra da loja é
        20 % de desconto a partir de R$ 500,00 (devia sair R$ 480,00). Abaixo de R$ 100,00 não há
        desconto; de R$ 100,00 até R$ 499,99 o desconto é de 10 %.
    """)
    objective = (
        "Há um bug no cálculo de descontos descrito em RELATO.md. Reproduza o problema, identifique a causa "
        "raiz, explique o comportamento incorreto, corrija pricing.py com a menor mudança adequada, crie um "
        "teste de regressão em test_pricing.py (sem apagar os testes existentes) e execute os testes."
    )

    def regression_fails_on_original() -> bool:
        """O teste novo do agente, rodado contra o pricing.py original, tem de reprovar."""
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "pricing.py").write_text(textwrap.dedent(_PRICING).lstrip("\n"), encoding="utf-8")
            shutil.copy(ws / "test_pricing.py", Path(tmp, "test_pricing.py"))
            proc = _pytest(Path(tmp), cwd=Path(tmp))
            return proc.returncode != 0 and " failed" in proc.stdout

    return {
        "name": "t05_desconto",
        "titulo": "Debugging e correção de bug",
        "objective": objective,
        "tools_required": ["read_file", "edit_file|write_file", "run_pytest|run_command|run_check"],
        "checks": {
            "compreensao": {
                "pricing.py alterado": lambda: _read(ws, "pricing.py") != textwrap.dedent(_PRICING).lstrip("\n"),
            },
            "execucao": {
                "600 → 480 e 500 → 400": lambda: _ok(ws, "import pricing as p; assert p.total_com_desconto(600)==480.0 and p.total_com_desconto(500)==400.0"),
                "faixas antigas preservadas": lambda: _ok(ws, "import pricing as p; assert p.total_com_desconto(150)==135.0 and p.total_com_desconto(50)==50.0 and p.total_com_desconto(99.99)==99.99"),
                "erro de total negativo preservado": lambda: _ok(ws, "import pricing as p\ntry:\n    p.desconto_percentual(-1)\nexcept ValueError:\n    pass\nelse:\n    raise SystemExit(1)"),
            },
            "verificacao": {
                "testes antigos mantidos": lambda: all(
                    name in _read(ws, "test_pricing.py") for name in ("def test_faixa_dez", "def test_sem_desconto")
                ) and len(_read(ws, "test_pricing.py")) > len(original_tests),
                "teste de regressão reprova no código original": regression_fails_on_original,
                "testes passam": lambda: _passes(ws),
            },
        },
    }


def _cenario_t06_arquitetura(ws: Path) -> dict:
    """T06 — arquitetura: diagnóstico pelo código e uma melhoria de baixo risco com testes antes e depois."""
    _w(ws, "loja/__init__.py", "")
    _w(ws, "loja/db.py", """
        import sqlite3

        def conectar(caminho=":memory:"):
            con = sqlite3.connect(caminho)
            con.execute("create table if not exists pedidos (id integer primary key, cliente text, valor real)")
            return con
    """)
    original = _w(ws, "loja/relatorio.py", """
        from loja.db import conectar

        def relatorio_clientes(con=None):
            # consulta, regra de negócio, formatação e impressão misturadas
            con = con or conectar()
            linhas = con.execute("select cliente, valor from pedidos").fetchall()
            totais = {}
            for cliente, valor in linhas:
                totais[cliente] = totais.get(cliente, 0) + valor
            saida = []
            for cliente in sorted(totais):
                total = totais[cliente]
                if total > 1000:
                    categoria = "ouro"
                elif total > 500:
                    categoria = "prata"
                else:
                    categoria = "bronze"
                saida.append(f"{cliente}: R$ {total:.2f} ({categoria})")
            texto = "\\n".join(saida)
            print(texto)
            return texto

        def categoria_cliente(con, cliente):
            # regra de categoria duplicada
            total = sum(v for (v,) in con.execute("select valor from pedidos where cliente = ?", (cliente,)))
            if total > 1000:
                return "ouro"
            elif total > 500:
                return "prata"
            return "bronze"
    """)
    _w(ws, "loja/cli.py", """
        import sys
        from loja.db import conectar
        from loja.relatorio import relatorio_clientes

        def main(argv=None):
            con = conectar((argv or sys.argv[1:] or [":memory:"])[0])
            relatorio_clientes(con)
            return 0
    """)
    _w(ws, "tests/test_relatorio.py", """
        from loja.db import conectar
        from loja.relatorio import categoria_cliente, relatorio_clientes


        def _con():
            con = conectar()
            con.executemany("insert into pedidos (cliente, valor) values (?, ?)",
                            [("ana", 600), ("ana", 500), ("bia", 300), ("caio", 501)])
            return con


        def test_relatorio():
            assert relatorio_clientes(_con()) == "ana: R$ 1100.00 (ouro)\\nbia: R$ 300.00 (bronze)\\ncaio: R$ 501.00 (prata)"


        def test_categoria():
            con = _con()
            assert categoria_cliente(con, "ana") == "ouro"
            assert categoria_cliente(con, "caio") == "prata"
            assert categoria_cliente(con, "zé") == "bronze"
    """)
    _w(ws, "pytest.ini", "[pytest]\npythonpath = .\n")
    objective = (
        "Analise a arquitetura do pacote Python loja/: identifique os módulos, mapeie as dependências entre "
        "eles, aponte acoplamento desnecessário, problemas de separação de responsabilidades e riscos de "
        "manutenção. Escreva o diagnóstico em ARQUITETURA.md. Depois proponha e aplique UMA melhoria de baixo "
        "risco que preserve o comportamento (sem criar abstrações desnecessárias), rodando os testes de tests/ "
        "antes e depois da mudança, e registre os dois resultados no ARQUITETURA.md."
    )
    hidden = """
        from loja.db import conectar
        from loja.relatorio import categoria_cliente, relatorio_clientes
        con = conectar()
        con.executemany("insert into pedidos (cliente, valor) values (?, ?)", [("x", 1000), ("y", 1000.01), ("z", 500)])
        assert relatorio_clientes(con) == "x: R$ 1000.00 (prata)\\ny: R$ 1000.01 (ouro)\\nz: R$ 500.00 (bronze)"
        assert [categoria_cliente(con, c) for c in "xyz"] == ["prata", "ouro", "bronze"]
    """
    doc = lambda: _read(ws, "ARQUITETURA.md")  # noqa: E731
    return {
        "name": "t06_arquitetura",
        "titulo": "Análise arquitetural e melhoria",
        "objective": objective,
        "tools_required": ["read_file", "edit_file|write_file", "run_pytest|run_command|run_check"],
        "checks": {
            "compreensao": {
                "ARQUITETURA.md cita os três módulos": lambda: all(m in doc() for m in ("db", "relatorio", "cli")),
                "aponta a regra duplicada ou a mistura de responsabilidades": lambda: bool(
                    re.search(r"duplica|repetid|mistur|responsabilidad", doc(), re.I)
                ),
            },
            "execucao": {
                "código melhorado": lambda: _read(ws, "loja/relatorio.py") != original
                or any(p.name not in {"__init__.py", "db.py", "relatorio.py", "cli.py"} for p in (ws / "loja").glob("*.py")),
                "comportamento preservado (sonda escondida)": lambda: _ok(ws, hidden),
            },
            "verificacao": {
                "testes passam depois": lambda: _passes(ws, "tests"),
                "resultado antes e depois registrado": lambda: len(re.findall(r"pass", doc(), re.I)) >= 2,
                "testes rodados ≥ 2 vezes": lambda ctx=None: True,
            },
        },
        "ctx_checks": {"verificacao": {"testes rodados ≥ 2 vezes": lambda ctx: ctx["test_runs"] >= 2}},
    }


_PROCESSA_LENTO = '''
"""Clientes distintos por ordem de primeira compra."""


def clientes_distintos(registros):
    """Lista dos clientes, sem repetição, na ordem em que aparecem pela primeira vez."""
    vistos = []
    for registro in registros:
        if registro["cliente"] not in vistos:
            vistos.append(registro["cliente"])
    return vistos
'''


def _cenario_t07_desempenho(ws: Path) -> dict:
    """T07 — desempenho: medir, achar o gargalo (busca em lista), otimizar e comparar com a mesma saída."""
    _w(ws, "dados.py", """
        import random


        def gerar(n=100_000, clientes=6_000, semente=42):
            rnd = random.Random(semente)
            return [{"id": i, "cliente": f"c{rnd.randrange(clientes):05d}", "valor": rnd.random() * 100} for i in range(n)]
    """)
    _w(ws, "processa.py", _PROCESSA_LENTO)
    _w(ws, "bench.py", """
        import time

        from dados import gerar
        from processa import clientes_distintos

        registros = gerar()
        inicio = time.perf_counter()
        resultado = clientes_distintos(registros)
        print(f"registros={len(registros)} distintos={len(resultado)} segundos={time.perf_counter() - inicio:.3f}")
    """)
    objective = (
        "O processamento em processa.py está lento com 100 mil registros (dados.py gera os registros; "
        "bench.py mede). Execute o benchmark para medir a versão inicial, identifique o gargalo com "
        "evidência, otimize clientes_distintos sem mudar a saída (mesma lista, mesma ordem), execute o "
        "benchmark de novo, verifique que a saída é idêntica à da versão inicial e escreva DESEMPENHO.md "
        "com os tempos medidos antes e depois, o gargalo e a comparação."
    )

    def faster_and_equal() -> bool:
        return _ok(ws, f"""
            import time, types
            from dados import gerar
            import processa
            lento = types.ModuleType('lento'); exec({_PROCESSA_LENTO!r}, lento.__dict__)
            regs = gerar(30_000)
            t = time.perf_counter(); a = lento.clientes_distintos(regs); t_lento = time.perf_counter() - t
            t = time.perf_counter(); b = processa.clientes_distintos(regs); t_novo = time.perf_counter() - t
            assert a == b, 'saída mudou'
            assert t_novo < t_lento / 3, (t_lento, t_novo)
            assert processa.clientes_distintos([]) == []
        """, timeout=200)

    doc = lambda: _read(ws, "DESEMPENHO.md")  # noqa: E731
    return {
        "name": "t07_desempenho",
        "titulo": "Desempenho",
        "objective": objective,
        "tools_required": ["run_command|run_script|run_check", "edit_file|write_file"],
        "checks": {
            "compreensao": {
                "DESEMPENHO.md criado": lambda: len(doc()) > 150,
                "gargalo identificado": lambda: bool(re.search(r"lista|list|in vistos|O\(n|quadr|set", doc(), re.I)),
            },
            "execucao": {
                "≥ 3x mais rápido com a mesma saída (sonda escondida)": faster_and_equal,
            },
            "verificacao": {
                "dois tempos medidos registrados": lambda: len(re.findall(r"\d+[.,]\d+\s*s", doc())) >= 2,
                "benchmark executado ≥ 2 vezes": lambda ctx=None: True,
                "tempos registrados vieram de execução real": lambda ctx=None: True,
            },
        },
        "ctx_checks": {
            "verificacao": {
                "benchmark executado ≥ 2 vezes": lambda ctx: ctx["tool_text"].count("segundos=") >= 2,
                "tempos registrados vieram de execução real": lambda ctx: any(
                    m in doc() for m in re.findall(r"segundos=(\d+\.\d+)", ctx["tool_text"])
                ),
            },
        },
    }


def _cenario_t08_api_clima(ws: Path) -> dict:
    """T08 — documentação e implementação: Open-Meteo pela documentação oficial, cliente e mocks."""
    objective = (
        "Pesquise a documentação oficial da API meteorológica gratuita Open-Meteo (https://open-meteo.com/en/docs) "
        "e registre em API.md: o endpoint de previsão, os parâmetros obrigatórios e opcionais usados, se exige "
        "autenticação, os limites de uso, o formato da resposta e os erros possíveis, com a URL de cada fonte. "
        "Depois crie clima.py com a função temperatura_atual(latitude, longitude) que consulta a API, valida "
        "os dados (latitude entre -90 e 90, longitude entre -180 e 180; senão ValueError), trata erros HTTP e "
        "resposta inválida levantando ClimaErro, e devolve um float. Crie test_clima.py com pytest usando mock "
        "(sem rede). Por fim, faça uma consulta real para São Paulo (-23.55, -46.63) e grave a resposta em "
        "consulta_real.json, separada dos testes com mock."
    )
    doc = lambda: _read(ws, "API.md")  # noqa: E731
    tests = lambda: _read(ws, "test_clima.py")  # noqa: E731

    def offline_tests_pass() -> bool:
        """Os testes do agente passam com a rede bloqueada (o mock é obrigatório)."""
        if not tests():
            return False
        conftest = ws / "_bloqueia_rede.py"
        conftest.write_text(
            "import socket\n"
            "def _block(*a, **k):\n    raise OSError('rede bloqueada na verificação')\n"
            "socket.socket.connect = _block\nsocket.create_connection = _block\n",
            encoding="utf-8",
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c",
                 "import _bloqueia_rede, sys, pytest; sys.exit(pytest.main(['-q','-p','no:cacheprovider','test_clima.py']))"],
                cwd=str(ws), capture_output=True, text=True, timeout=120,
            )
            return proc.returncode == 0 and " passed" in proc.stdout
        finally:
            conftest.unlink(missing_ok=True)

    def real_json() -> bool:
        try:
            data = json.loads(_read(ws, "consulta_real.json"))
        except ValueError:
            return False
        blob = json.dumps(data)
        return "latitude" in blob and ("current" in blob or "temperature" in blob)

    return {
        "name": "t08_api_clima",
        "titulo": "Documentação e implementação",
        "objective": objective,
        "browser_mode": "headless",
        "tools_required": ["browser|http_request", "write_file|edit_file", "run_pytest|run_command|run_check"],
        "checks": {
            "compreensao": {
                "API.md cita o endpoint de previsão": lambda: "api.open-meteo.com/v1/forecast" in doc(),
                "API.md cita parâmetros e autenticação": lambda: all(k in doc().lower() for k in ("latitude", "longitude"))
                and bool(re.search(r"chave|api key|autentica", doc(), re.I)),
            },
            "execucao": {
                "validação de coordenadas": lambda: _ok(ws, "import clima\nfor a in [(91,0),(0,181)]:\n    try:\n        clima.temperatura_atual(*a)\n    except ValueError:\n        pass\n    else:\n        raise SystemExit(a)"),
                "ClimaErro existe": lambda: _ok(ws, "import clima; assert issubclass(clima.ClimaErro, Exception)"),
                "consulta real gravada": real_json,
            },
            "verificacao": {
                "testes com mock passam sem rede": offline_tests_pass,
                "documentação oficial foi lida": lambda ctx=None: True,
            },
        },
        "ctx_checks": {
            "verificacao": {"documentação oficial foi lida": lambda ctx: "open-meteo.com" in ctx["tool_text"].lower()},
        },
    }


def _cenario_t09_logs(ws: Path) -> dict:
    """T09 — automação: relatórios JSON e HTML de logs, com arquivos vazios/inválidos e reexecução."""
    _w(ws, "logs/app1.log", """
        2026-11-01 10:00:01 INFO iniciado
        2026-11-01 10:00:02 WARNING disco em 85%
        2026-11-01 10:00:03 ERROR falha ao gravar pedido 17
        2026-11-01 10:00:04 ERROR falha ao gravar pedido 18
        2026-11-01 10:00:05 INFO ok
    """)
    _w(ws, "logs/app2.log", """
        2026-11-01 11:00:00 WARNING fila lenta
        2026-11-01 11:00:01 WARNING fila lenta
        2026-11-01 11:00:02 INFO texto com a palavra error minúscula não conta
        2026-11-01 11:00:03 ERROR timeout no serviço de pagamento
    """)
    _w(ws, "logs/vazio.log", "")
    _wb(ws, "logs/binario.log", b"\xff\xfe\x00\x81ERROR?\x00\x9c")
    _w(ws, "logs/notas.txt", "ERROR isto não é .log e não deve ser contado\n")
    objective = (
        "Crie analisa_logs.py que lê todos os arquivos .log da pasta logs/ (só .log), conta as linhas de nível "
        "ERROR e WARNING (o nível é a palavra em maiúsculas depois da data e hora) por arquivo e no total, e gera "
        "relatorio.json e relatorio.html na pasta atual. Arquivos vazios entram com contagem zero; arquivos "
        "inválidos (que não são texto UTF-8) são listados em \"invalidos\" no JSON sem derrubar a execução. "
        "Rodar o script de novo deve produzir exatamente os mesmos relatórios, sem duplicar resultados. "
        "Use no JSON as chaves \"arquivos\" (um objeto por nome de arquivo com \"ERROR\" e \"WARNING\"), \"total\" "
        "(com \"ERROR\" e \"WARNING\") e \"invalidos\" (lista de nomes). Crie testes com pytest e execute-os."
    )

    def run_twice() -> dict:
        out = {}
        for i in (1, 2):
            proc = subprocess.run([sys.executable, "analisa_logs.py"], cwd=str(ws), capture_output=True, text=True, timeout=60)
            out[i] = (proc.returncode, _read(ws, "relatorio.json"), _read(ws, "relatorio.html"))
        return out

    cache: dict = {}

    def runs() -> dict:
        if not cache and (ws / "analisa_logs.py").exists():
            cache.update(run_twice())
        return cache

    def report() -> dict:
        try:
            return json.loads(runs()[2][1])
        except (KeyError, ValueError):
            return {}

    return {
        "name": "t09_logs",
        "titulo": "Automação de arquivos",
        "objective": objective,
        "tools_required": ["write_file|edit_file", "run_pytest|run_command|run_check|run_script"],
        "checks": {
            "compreensao": {
                "analisa_logs.py criado": lambda: (ws / "analisa_logs.py").exists(),
                "script roda sem erro": lambda: bool(runs()) and runs()[1][0] == 0 and runs()[2][0] == 0,
            },
            "execucao": {
                "total ERROR=3 WARNING=3": lambda: report().get("total") in ({"ERROR": 3, "WARNING": 3},)
                or (report().get("total", {}).get("ERROR"), report().get("total", {}).get("WARNING")) == (3, 3),
                "por arquivo correto": lambda: (report().get("arquivos", {}).get("app1.log", {}).get("ERROR"),
                                                report().get("arquivos", {}).get("app2.log", {}).get("WARNING")) == (2, 2),
                "vazio com zero e binário inválido": lambda: report().get("arquivos", {}).get("vazio.log", {}).get("ERROR") == 0
                and any("binario" in str(x) for x in report().get("invalidos", [])),
                ".txt ignorado": lambda: "notas.txt" not in json.dumps(report()),
                "HTML gerado com as contagens": lambda: bool(runs()) and "<" in runs()[2][2] and "app1.log" in runs()[2][2],
            },
            "verificacao": {
                "reexecução idêntica": lambda: bool(runs()) and runs()[1][1:] == runs()[2][1:],
                "testes do agente passam": lambda: any(ws.glob("test_*.py")) and _passes(ws),
            },
        },
    }


_LISTA_HTML = """
<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"><title>Clientes</title>
<style>body{font-family:sans-serif} li{padding:2px 4px;border-bottom:1px solid #eee}</style></head>
<body>
<input id="filtro" placeholder="filtrar">
<p id="contagem"></p>
<ul id="lista"></ul>
<script src="dados.js"></script>
<script src="app.js"></script>
</body>
</html>
"""

_LISTA_APP = """
function renderLista(itens) {
  const lista = document.getElementById('lista');
  lista.innerHTML = '';
  for (const item of itens) {
    lista.insertAdjacentHTML('beforeend', '<li data-id="' + item.id + '">' + item.nome + ' — ' + item.cidade + '</li>');
    document.getElementById('contagem').textContent = lista.offsetHeight + 'px';
  }
  document.getElementById('contagem').textContent = itens.length + ' clientes';
}

document.getElementById('filtro').addEventListener('input', (e) => {
  const termo = e.target.value.toLowerCase();
  renderLista(DADOS.filter((d) => d.nome.toLowerCase().includes(termo)));
});

window.__inicio = performance.now();
renderLista(DADOS);
window.__renderMs = performance.now() - window.__inicio;
"""

_LISTA_DADOS = """
const DADOS = Array.from({ length: 10000 }, (_, i) => ({
  id: i, nome: 'Cliente ' + i, cidade: ['Recife', 'Natal', 'Belém', 'Goiânia'][i % 4],
}));
"""

_LISTA_SCRIPT = """async () => {
  const filtro = document.getElementById('filtro');
  const total = document.querySelectorAll('#lista li').length;
  const ms = window.__renderMs;
  filtro.value = 'cliente 999';
  filtro.dispatchEvent(new Event('input'));
  await new Promise(r => setTimeout(r, 300));
  const filtrados = [...document.querySelectorAll('#lista li')].map(li => li.dataset.id);
  return { total, ms, filtrados, contagem: document.getElementById('contagem').textContent };
}"""


def _cenario_t10_lista_lenta(ws: Path) -> dict:
    """T10 — problema composto: lista de 10 mil itens lenta; medir, pesquisar, corrigir e validar visualmente."""
    _w(ws, "web/index.html", _LISTA_HTML)
    _w(ws, "web/app.js", _LISTA_APP)
    _w(ws, "web/dados.js", _LISTA_DADOS)
    objective = (
        "A página web/index.html demora a renderizar a lista de 10 mil clientes. Analise web/app.js, meça o "
        "tempo de renderização no navegador antes da mudança (a página expõe window.__renderMs), identifique "
        "os gargalos, pesquise soluções quando precisar, otimize renderLista mantendo o comportamento (os 10 000 "
        "itens <li data-id> no DOM, o filtro e o texto de contagem \"N clientes\"), meça de novo no navegador, "
        "confira visualmente com uma screenshot e escreva RELATORIO.md com os gargalos, a solução, os tempos "
        "antes e depois e as limitações."
    )
    cache: dict = {}

    def measure(folder: Path) -> dict:
        try:
            return _browser_page((folder / "index.html").as_uri(), 1280, script=_LISTA_SCRIPT)
        except Exception as exc:
            return {"erro": str(exc)[:200]}

    def before_after() -> tuple[dict, dict]:
        if not cache:
            with tempfile.TemporaryDirectory() as tmp:
                original = Path(tmp)
                (original / "index.html").write_text(_LISTA_HTML, encoding="utf-8")
                (original / "app.js").write_text(_LISTA_APP, encoding="utf-8")
                (original / "dados.js").write_text(_LISTA_DADOS, encoding="utf-8")
                cache["antes"] = measure(original)
            cache["depois"] = measure(ws / "web")
        return cache["antes"], cache["depois"]

    def behavior() -> bool:
        antes, depois = before_after()
        return (
            depois.get("total") == 10000
            and depois.get("filtrados") == antes.get("filtrados")
            and bool(re.match(r"^\d+ clientes$", str(depois.get("contagem") or "")))
        )

    def faster() -> bool:
        antes, depois = before_after()
        try:
            return float(depois["ms"]) < float(antes["ms"]) / 3
        except (KeyError, TypeError, ValueError):
            return False

    doc = lambda: _read(ws, "RELATORIO.md")  # noqa: E731
    return {
        "name": "t10_lista_lenta",
        "titulo": "Problema multifuncional",
        "objective": objective,
        "browser_mode": "headless",
        "tools_required": ["read_file", "edit_file|write_file", "browser"],
        "checks": {
            "compreensao": {
                "RELATORIO.md criado": lambda: len(doc()) > 200,
                "gargalo apontado (reflow forçado / inserção item a item)": lambda: bool(
                    re.search(r"innerHTML|reflow|layout|offsetHeight|fragment", doc(), re.I)
                ),
            },
            "execucao": {
                "app.js alterado": lambda: _read(ws, "web/app.js") != textwrap.dedent(_LISTA_APP).lstrip("\n"),
                "comportamento preservado (10 000 itens, filtro, contagem)": behavior,
                "≥ 3x mais rápido no navegador": faster,
            },
            "verificacao": {
                "tempos antes e depois registrados": lambda: len(re.findall(r"\d+(?:[.,]\d+)?\s*ms", doc())) >= 2,
                "agente mediu no navegador": lambda ctx=None: True,
                "agente capturou screenshot": lambda ctx=None: True,
            },
        },
        "ctx_checks": {
            "verificacao": {
                "agente mediu no navegador": lambda ctx: "index.html" in ctx["browser_urls"],
                "agente capturou screenshot": lambda ctx: ctx["screenshots"] > 0,
            },
        },
    }


CENARIOS = [
    _cenario_t01_text_analyzer,
    _cenario_t02_dashboard,
    _cenario_t03_pesquisa_vue,
    _cenario_t04_ias_externas,
    _cenario_t05_desconto,
    _cenario_t06_arquitetura,
    _cenario_t07_desempenho,
    _cenario_t08_api_clima,
    _cenario_t09_logs,
    _cenario_t10_lista_lenta,
]


# ────────────────────────────────────────────────────────────────────── contexto do run


_AI_HOSTS = ("chatgpt.com", "chat.openai.com", "gemini.google.com", "claude.ai", "copilot.microsoft.com")


def run_context(db: Path) -> dict:
    """Lê do banco isolado o que as ferramentas fizeram de verdade no run.

    Args:
        db: banco SQLite do cenário.

    Returns:
        Texto de todas as respostas de ferramenta, URLs abertas no navegador, screenshots,
        execuções de teste e respostas de IA externa efetivamente capturadas.
    """
    con = sqlite3.connect(str(db))
    rows = con.execute(
        "select provider, coalesce(request_json, ''), coalesce(response_json, ''), success "
        "from operation_attempts where kind = 'tool'"
    ).fetchall()
    con.close()
    texts: list[str] = []
    urls: list[str] = []
    screenshots = 0
    test_runs = 0
    ai_pages = 0
    ai_answers = 0
    browser_results: list[dict] = []
    for tool, request, response, success in rows:
        texts.append(str(response))
        try:
            req = json.loads(request) if request else {}
        except ValueError:
            req = {}
        if not isinstance(req, dict):
            req = {}
        action = str(req.get("action") or "")
        if tool == "browser":
            try:
                parsed = json.loads(response) if response else {}
                inner = parsed.get("result", parsed) if isinstance(parsed, dict) else {}
                if isinstance(inner, dict) and inner.get("url"):
                    browser_results.append({"url": inner.get("url"), "title": inner.get("title"), "status": inner.get("status")})
            except ValueError:
                pass
            url = str(req.get("url") or "")
            if url:
                urls.append(url)
            if action == "screenshot" and success:
                screenshots += 1
            if any(host in url for host in _AI_HOSTS):
                ai_pages += 1
            # Resposta de IA lida pela própria ferramenta: snapshot numa página de IA com texto
            # substancial sobre o assunto perguntado (não a página de login).
            if action == "snapshot" and success and any(host in str(response) for host in _AI_HOSTS):
                low = str(response).lower()
                if len(low) > 1500 and "fastapi" in low and not re.search(r"log in|entrar|sign in|captcha", low[:600]):
                    ai_answers += 1
        if tool in {"run_pytest", "run_check"} or (tool == "run_command" and "pytest" in str(request)):
            test_runs += 1
        if tool == "ask_external_ai" and success:
            try:
                if json.loads(response).get("answer"):
                    ai_answers += 1
            except (ValueError, AttributeError):
                pass
        if tool == "ask_external_ai":
            ai_pages += 1
    return {
        "tool_text": "\n".join(texts),
        "browser_urls": "\n".join(urls),
        "screenshots": screenshots,
        "test_runs": test_runs,
        "ai_pages_opened": ai_pages,
        "ai_answers_captured": ai_answers,
        "browser_results": browser_results,
    }


# ────────────────────────────────────────────────────────────────────── pontuação


def _ratio(results: dict[str, bool]) -> float:
    """Fração de critérios cumpridos (1.0 quando não há critério da dimensão)."""
    return 1.0 if not results else sum(results.values()) / len(results)


def _required_tools_used(required: list[str], usage: dict) -> float:
    """Fração dos grupos de ferramenta exigidos que tiveram pelo menos uma chamada bem-sucedida."""
    if not required:
        return 1.0
    ok = 0
    for group in required:
        names = group.split("|")
        if any(usage.get(n, {}).get("chamadas", 0) > usage.get(n, {}).get("falhas", 0) for n in names):
            ok += 1
    return ok / len(required)


def pontuar(report: dict, checks: dict[str, dict[str, bool]], required: list[str]) -> dict:
    """Converte medidas objetivas em notas de 0 a 5 por dimensão.

    Fórmula fixa (o detalhe e a justificativa estão em docs/architecture/bateria.md):

    - compreensão, execução e verificação: 5 × fração dos critérios da dimensão cumpridos;
    - ferramentas: 5 × fração dos grupos de ferramenta exigidos usados com sucesso, menos 1 quando
      mais da metade das chamadas falhou;
    - planejamento: 5 com plano de 2 a 15 tarefas e sem estagnação; −1 por estagnação, −1 com mais
      de 3 replanejamentos; 1 quando o run não chegou a planejar (≤ 1 tarefa);
    - autonomia: 5 concluído no tempo, 3 falhou com mensagem, 1 tempo esgotado ou estagnado,
      0 pausado pedindo humano.

    Args:
        report: relatório do `run_scenario`.
        checks: critérios avaliados, por dimensão.
        required: grupos de ferramentas exigidos pelo cenário.

    Returns:
        `{dimensão: nota}` e o total.
    """
    notas: dict[str, float] = {}
    for dim in ("compreensao", "execucao", "verificacao"):
        notas[dim] = round(5 * _ratio(checks.get(dim, {})), 1)
    usage = report.get("ferramentas", {})
    calls = sum(v["chamadas"] for v in usage.values())
    fails = sum(v["falhas"] for v in usage.values())
    tools = 5 * _required_tools_used(required, usage)
    if calls and fails / calls > 0.5:
        tools -= 1
    notas["ferramentas"] = round(max(0.0, tools), 1)
    tasks = int(report.get("tarefas") or 0)
    if tasks <= 1:
        plan = 1.0
    else:
        plan = 5.0 if 2 <= tasks <= 15 else 3.0
        plan -= min(2, int(report.get("estagnacoes") or 0))
        if int(report.get("replanejamentos") or 0) > 3:
            plan -= 1
    notas["planejamento"] = max(0.0, plan)
    status = report.get("run_status")
    if report.get("pausas"):
        auto = 0.0
    elif report.get("tempo_esgotado") or status in {"running", "stalled"}:
        auto = 1.0
    elif status == "completed":
        auto = 5.0
    else:
        auto = 3.0
    notas["autonomia"] = auto
    notas["total"] = round(sum(notas[d] for d in DIMENSOES), 1)
    return notas


def _classificacao(total: float) -> str:
    """Faixa da bateria (classificação interna, não um benchmark universal)."""
    if total >= 270:
        return "Excelente nesta bateria"
    if total >= 225:
        return "Bastante competente"
    if total >= 180:
        return "Multifuncional em evolução"
    if total >= 100:
        return "Funcional limitado"
    return "Insuficiente"


def _estado(report: dict, checks: dict[str, dict[str, bool]], blocked: bool) -> str:
    """PASSOU, PARCIAL, FALHOU ou BLOQUEADO, a partir do aceite medido."""
    flat = [v for dim in checks.values() for v in dim.values()]
    ratio = sum(flat) / len(flat) if flat else 0.0
    if blocked and ratio < 1:
        return "BLOQUEADO"
    if ratio == 1:
        return "PASSOU"
    if ratio >= 0.5:
        return "PARCIAL"
    return "FALHOU"


# ────────────────────────────────────────────────────────────────────── execução


def _git_head() -> str:
    """Commit atual do Callidus (para comparar versões no histórico)."""
    proc = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "src"], capture_output=True, text=True).stdout.strip()
    return proc.stdout.strip() + ("+mudanças" if dirty else "")


async def run_one(scenario_fn, *, model: str, provider: str, time_limit: float, work: Path) -> dict:
    """Roda um cenário da bateria e devolve o relatório pontuado.

    Args:
        scenario_fn: preparador do cenário.
        model: modelo do run.
        provider: provedor configurado.
        time_limit: limite de tempo do Callidus, em segundos.
        work: pasta base desta bateria.

    Returns:
        O relatório do `run_scenario` acrescido de critérios, notas e estado.
    """
    spec_holder: dict = {}

    def prepare(ws: Path) -> dict:
        spec = scenario_fn(ws)
        spec_holder.update(spec)
        return {"name": spec["name"], "objective": spec["objective"], "accept": {}}

    prepare.__name__ = scenario_fn.__name__
    peek = scenario_fn.__name__.replace("_cenario_", "")
    # O modo do navegador é do cenário; preparamos uma vez numa pasta descartável para lê-lo.
    with tempfile.TemporaryDirectory() as tmp:
        browser_mode = scenario_fn(Path(tmp)).get("browser_mode", "off")
    report = await avaliar.run_scenario(
        prepare,
        model_id=model,
        provider=provider,
        max_steps=400,
        browser_mode=browser_mode,
        time_limit=time_limit,
        work=work,
    )
    spec = spec_holder
    ctx = run_context(work / f"{peek}.db")
    checks: dict[str, dict[str, bool]] = {}
    for dim, items in spec["checks"].items():
        checks[dim] = {}
        for name, fn in items.items():
            override = spec.get("ctx_checks", {}).get(dim, {}).get(name)
            answer_rx = spec.get("answer_checks", {}).get(dim, {}).get(name)
            try:
                if override is not None:
                    value = bool(override(ctx))
                elif answer_rx is not None:
                    value = bool(re.search(answer_rx, report.get("resposta_final", ""), re.I))
                else:
                    value = bool(fn())
            except Exception:
                value = False
            checks[dim][name] = value
    blocked = bool(spec.get("blocked_if", lambda _c: False)(ctx))
    notas = pontuar(report, checks, spec.get("tools_required", []))
    report.update(
        {
            "cenario": spec["name"],
            "titulo": spec["titulo"],
            "browser_mode": browser_mode,
            "criterios": checks,
            "notas": notas,
            "estado": _estado(report, checks, blocked),
            "bloqueado": blocked,
            "contexto": {k: v for k, v in ctx.items() if k != "tool_text"},
            "workspace": str(work / peek),
        }
    )
    return report


async def main() -> None:
    """Roda a bateria (ou parte dela), grava o relatório e acrescenta ao histórico."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="atual")
    parser.add_argument("--model", default="gpt-oss:20b")
    parser.add_argument("--provider", default="meu_ollama")
    parser.add_argument("--time-limit", type=float, default=TIME_LIMIT)
    parser.add_argument("--only", default="", help="filtra cenários por parte do nome (vírgulas)")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    work = WORK / args.label
    filters = [f for f in args.only.split(",") if f]
    reports = []
    for scenario_fn in CENARIOS:
        if filters and not any(f in scenario_fn.__name__ for f in filters):
            continue
        print(f"→ {scenario_fn.__name__} ...", flush=True)
        started = time.monotonic()
        report = await run_one(
            scenario_fn, model=args.model, provider=args.provider, time_limit=args.time_limit, work=work
        )
        reports.append(report)
        print(
            f"   {report['estado']} nota={report['notas']['total']}/30 run={report['run_status']} "
            f"tempo_esgotado={report['tempo_esgotado']} {round(time.monotonic() - started)}s "
            f"ferramentas={ {k: v['chamadas'] for k, v in report['ferramentas'].items()} }",
            flush=True,
        )
        for dim, items in report["criterios"].items():
            for name, value in items.items():
                print(f"      [{'x' if value else ' '}] {dim}: {name}", flush=True)

    total = round(sum(r["notas"]["total"] for r in reports), 1)
    summary = {
        "label": args.label,
        "quando": datetime.now(UTC).isoformat(timespec="seconds"),
        "callidus": _git_head(),
        "modelo": args.model,
        "provedor": args.provider,
        "limite_s": args.time_limit,
        "cenarios": len(reports),
        "pontuacao": total,
        "maximo": 30 * len(reports),
        "classificacao": _classificacao(total * 10 / max(1, len(reports))),
        "estados": {r["cenario"]: r["estado"] for r in reports},
        "notas": {r["cenario"]: r["notas"] for r in reports},
    }
    (OUT / f"{args.label}.json").write_text(
        json.dumps({"resumo": summary, "cenarios": reports}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    with (OUT / "historico.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
