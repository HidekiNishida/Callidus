"""
Arquivo: src/agent/orchestrator/execution/tool_results.py
Nome: tool_results.py
Propósito: interpretar o resultado de uma ferramenta determinística.
Responsabilidade: camada de aplicação — distinguir "a ferramenta falhou" de "a ferramenta funcionou e o resultado foi negativo".
Componentes: is_informative_test_result, test_summary.
Dependências: nenhuma (funções puras sobre o dicionário de resultado da ferramenta).
Observações: rodar a suíte e ver os testes falharem é resultado, não falha de ferramenta — repetir a mesma chamada devolveria a mesma falha.
"""

from __future__ import annotations

from typing import Any

TEST_TOOLS = ("run_pytest", "pytest")


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
