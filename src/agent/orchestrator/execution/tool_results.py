"""
Arquivo: src/agent/orchestrator/execution/tool_results.py
Nome: tool_results.py
Propósito: interpretar o resultado de uma ferramenta determinística.
Responsabilidade: camada de aplicação — distinguir "a ferramenta falhou" de "a ferramenta funcionou e o resultado foi negativo".
Componentes: is_informative_test_result, test_summary, environment_finding.
Dependências: nenhuma (funções puras sobre o dicionário de resultado da ferramenta).
Observações: rodar a suíte e ver os testes falharem é resultado, não falha de ferramenta — repetir a mesma chamada devolveria a mesma falha.
"""

from __future__ import annotations

from typing import Any

TEST_TOOLS = ("run_pytest", "pytest")

#: Ferramentas que só inspecionam o ambiente: uma "falha" delas pode ser a própria resposta.
INSPECTION_TOOLS = ("git_status", "git_diff", "git_log")

#: Respostas determinísticas do ambiente → descoberta legível. Repetir a chamada devolve o mesmo.
_ENVIRONMENT_ANSWERS: tuple[tuple[str, str], ...] = (
    ("not a git repository", "a pasta do projeto não é um repositório git"),
    ("não é um repositório git", "a pasta do projeto não é um repositório git"),
)


def environment_finding(tool_id: str, out: dict) -> str | None:
    """A inspeção "falhou" porque o ambiente respondeu algo determinístico — isso é a descoberta.

    Visto na avaliação real (`gpt-oss:20b` e `qwen3-vl:8b`): o plano começa com `git_status` numa
    pasta que não é repositório; a etapa era repetida três vezes, idêntica, até a estagnação
    descartar o plano inteiro e o run estourar o limite de passos. A pergunta da etapa ("qual o
    estado do repositório?") já estava respondida: não há repositório.

    Args:
        tool_id: identificador da ferramenta executada.
        out: resultado devolvido pela ferramenta.

    Returns:
        A descoberta em uma frase, ou `None` quando é falha de verdade (ou não é inspeção).
    """
    if tool_id not in INSPECTION_TOOLS or out.get("success"):
        return None
    text = f"{out.get('stderr') or ''} {out.get('error') or ''} {out.get('stdout') or ''}".casefold()
    for needle, finding in _ENVIRONMENT_ANSWERS:
        if needle in text:
            return finding
    return None


def is_informative_test_result(tool_id: str, out: dict) -> bool:
    """A ferramenta rodou e o resultado é um veredito, não uma falha de execução.

    `run_pytest` que termina com código de saída diferente de zero e saída de texto é a suíte
    **reprovando** — a ferramenta funcionou. Só há falha de ferramenta quando o comando nem
    chegou a rodar (executável ausente, timeout, caminho bloqueado).

    Args:
        tool_id: identificador da ferramenta executada.
        out: resultado devolvido pela ferramenta.

    Returns:
        `True` quando o resultado informa uma reprovação de testes (e não uma ferramenta quebrada).
    """
    if tool_id not in TEST_TOOLS:
        return False
    if out.get("success"):
        return False
    if out.get("exit_code") is None:
        return False
    return bool(str(out.get("stdout") or "").strip() or str(out.get("stderr") or "").strip())


def test_summary(out: dict) -> str:
    """Resumo curto do que a suíte contou.

    Args:
        out: resultado devolvido pela ferramenta de testes.

    Returns:
        A última linha não vazia da saída (limitada) ou o código de saída.
    """
    text = str(out.get("stdout") or out.get("stderr") or "").strip()
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1][:200] if lines else f"código de saída {out.get('exit_code')}"


def as_dict(value: Any) -> dict:
    """Normaliza um valor qualquer em dicionário (resultados de ferramenta são dicionários).

    Args:
        value: valor devolvido por uma ferramenta.

    Returns:
        O próprio dicionário, ou um dicionário vazio quando o valor não é um mapeamento.
    """
    return dict(value) if isinstance(value, dict) else {}
