"""
Arquivo: src/agent/providers/ollama_policy.py
Nome: ollama_policy.py
Propósito: adaptar a requisição e a resposta do Ollama à família do modelo (janela, saída, amostragem, formato).
Responsabilidade: camada de infraestrutura — política por família de modelo do adaptador Ollama; nenhuma regra de negócio.
Componentes: ModelFamily, family_for, purpose_class, apply_request_policy, split_reasoning, tool_calls_from_text, context_saturated.
Dependências: agent.providers.base (contrato e estimativa de tokens).
Observações: tudo o que a política preenche é padrão — o que vier da configuração (`generation`) vence sempre.

Por que existe
--------------
O Ollama decide sozinho três coisas que o Callidus precisa controlar:

1. **Janela (`num_ctx`)**: sem o campo, o servidor usa o próprio padrão (4 096 tokens em máquinas
   com menos de 24 GiB de VRAM, conforme a versão). O Callidus orça o prompt para
   `context_limit` (8 192 por padrão); o excedente era cortado **em silêncio** pelo servidor — e o
   que se perde é o começo da conversa: as regras e o formato de saída.
2. **Saída (`num_predict`)**: sem o campo, o padrão é ilimitado (até encher a janela). Um plano
   que entra em repetição consumia minutos (medido: 7 626 tokens em 466 s num plano).
3. **Amostragem**: os padrões do Modelfile do `qwen3` são os do modo de raciocínio
   (temperature 0,6, top_p 0,95); o Callidus usa o modo direto (`think: false`), para o qual o
   fabricante recomenda temperature 0,7, top_p 0,8, top_k 20.

Famílias "sempre raciocinam" (`gpt-oss`, `deepseek-r1`) ficam como estavam: o raciocínio consome
`num_predict`, e o modelo de referência da avaliação (`gpt-oss:20b`) não pode mudar de
comportamento sem uma medição nova.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from agent.providers.base import ChatCompletionRequest, ToolCall, estimate_text_tokens

# Margem de segurança entre o que se estima e o que o servidor conta, em tokens.
_WINDOW_MARGIN = 256
# A janela cresce em degraus: trocar `num_ctx` faz o Ollama recarregar o modelo, então a mesma
# conversa precisa cair sempre no mesmo degrau em vez de variar a cada chamada.
_WINDOW_STEP = 4096
# Teto da janela que a política pede sozinha. Acima disso, só por configuração explícita.
_WINDOW_CEILING = 32768
# Raciocínio ligado: a cadeia de pensamento sai do mesmo `num_predict` que a resposta.
_THINKING_ALLOWANCE = 4096
# Teto de saída das respostas curtas (plano, JSON, resposta ao usuário), em tokens.
_SHORT_OUTPUT = 2048


@dataclass(frozen=True)
class ModelFamily:
    """O que o adaptador sabe de uma família de modelos servida pelo Ollama.

    Atributos:
        name: rótulo da família (aparece nos metadados da inferência).
        manage_window: a política define `num_ctx` e `num_predict` quando a configuração não define.
        sampling: amostragem padrão por classe de finalidade (`structured`, `code`, `prose`).
        thinking_sampling: amostragem quando o raciocínio está ligado.
    """

    name: str
    manage_window: bool = True
    sampling: dict[str, dict[str, Any]] = field(default_factory=dict)
    thinking_sampling: dict[str, Any] = field(default_factory=dict)


# Qwen3 no modo direto. Os valores de `prose` são a recomendação do fabricante para o modo sem
# raciocínio; `structured` e `code` baixam a temperatura porque um JSON ou um trecho de código com
# um caractere errado é descartado inteiro — não há meio-acerto. Não é guloso (temperature 0):
# o fabricante desaconselha, pela repetição infinita que provoca.
_QWEN3 = ModelFamily(
    name="qwen3",
    sampling={
        "structured": {"temperature": 0.3, "top_p": 0.8, "top_k": 20, "min_p": 0.0},
        "code": {"temperature": 0.5, "top_p": 0.8, "top_k": 20, "min_p": 0.0},
        "prose": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0},
    },
    thinking_sampling={"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0.0},
)
_ALWAYS_REASONING = ModelFamily(name="always_reasoning", manage_window=False)
_GENERIC = ModelFamily(name="generic")

_ALWAYS_REASONING_TOKENS = ("gpt-oss", "deepseek-r1", "deepseek-reasoner")


def family_for(model_id: str) -> ModelFamily:
    """Família do modelo pelo identificador do Ollama.

    Args:
        model_id: nome do modelo (`qwen3:8b`, `gpt-oss:20b`, `llama3.2`...).

    Returns:
        A família; modelos desconhecidos caem na genérica (janela gerida, amostragem do Modelfile).
    """
    low = (model_id or "").lower()
    if any(token in low for token in _ALWAYS_REASONING_TOKENS):
        return _ALWAYS_REASONING
    if "qwen3" in low:
        return _QWEN3
    return _GENERIC


_PURPOSE_CLASS = {
    "plan": "structured",
    "automation": "structured",
    "classify": "structured",
    "operation": "code",
    "final_answer": "prose",
    "chat": "prose",
    "chat_streaming": "prose",
    "agent_query": "prose",
}


def purpose_class(purpose: str | None, *, structured: bool = False) -> str | None:
    """Classe de amostragem de uma chamada.

    Args:
        purpose: finalidade declarada pela chamada (`plan`, `operation`, `final_answer`...).
        structured: a requisição pede formato estruturado (`response_format`).

    Returns:
        `structured`, `code` ou `prose`; `None` quando a finalidade é desconhecida (sem padrão).
    """
    if structured:
        return "structured"
    return _PURPOSE_CLASS.get((purpose or "").strip().lower())


def _round_up(value: int, step: int) -> int:
    """Arredonda para cima até o próximo múltiplo de `step`."""
    return ((max(1, value) + step - 1) // step) * step


def apply_request_policy(body: dict[str, Any], request: ChatCompletionRequest) -> dict[str, Any]:
    """Completa as opções do corpo `/api/chat` com os padrões da família do modelo.

    Args:
        body: corpo já montado (modelo, mensagens, `think`, `options` da configuração).
        request: requisição original, com perfil, ferramentas e finalidade.

    Returns:
        Metadados da decisão (`family`, `num_ctx`, `num_predict`, `sampling`), para a observabilidade.

    Observações:
        Altera `body["options"]` no lugar. Uma chave que a configuração já trouxe nunca é trocada.
        A janela pedida cobre o prompt estimado + a reserva de saída + margem; quando o perfil já
        cobre, é o `context_limit` do perfil — estável entre chamadas, para o Ollama não recarregar
        o modelo. A saída (`num_predict`) é curta (2 048) para plano, JSON e resposta, e o resto da
        janela para código; nunca passa da janela.
    """
    family = family_for(request.profile.model_id)
    options: dict[str, Any] = dict(body.get("options") or {})
    meta: dict[str, Any] = {"family": family.name}
    thinking = bool(body.get("think"))
    sampling_class = purpose_class(request.purpose, structured=request.response_format is not None)
    if family.manage_window:
        reserve = max(int(request.profile.output_reserve or 0), 0)
        allowance = _THINKING_ALLOWANCE if thinking else 0
        prompt = sum(estimate_text_tokens(m.content or "") for m in request.messages)
        if request.tools:
            prompt += estimate_text_tokens(json.dumps(request.tools, ensure_ascii=False))
        configured = int(options.get("num_predict") or 0)
        if "num_ctx" not in options:
            # A janela cobre o prompt + a saída mínima garantida + o raciocínio + margem.
            needed = prompt + (configured if configured > 0 else reserve) + allowance + _WINDOW_MARGIN
            window = int(request.profile.context_limit or 0)
            if needed > window:
                window = min(_WINDOW_CEILING, _round_up(needed, _WINDOW_STEP))
                meta["window_grown"] = True
            if window > 0:
                options["num_ctx"] = window
        if "num_predict" not in options and reserve > 0:
            window = int(options.get("num_ctx") or 0)
            remaining = window - prompt - _WINDOW_MARGIN if window else reserve + allowance
            floor = reserve + allowance
            if sampling_class in {"structured", "prose"}:
                # Plano, JSON e resposta ao usuário são curtos (medido: até ~430 tokens); o
                # teto curto corta a repetição sem fim sem cortar a resposta normal.
                target = max(reserve, _SHORT_OUTPUT) + allowance
            else:
                # Código e finalidade desconhecida: o que sobra da janela. Um arquivo inteiro
                # cabe, e a janela continua sendo o limite — nunca ilimitado.
                target = max(floor, remaining)
            options["num_predict"] = min(target, max(floor, remaining))
    defaults = family.thinking_sampling if thinking and family.thinking_sampling else family.sampling.get(sampling_class or "", {})
    applied = []
    for key, value in defaults.items():
        if key not in options:
            options[key] = value
            applied.append(key)
    if applied:
        meta["sampling"] = "thinking" if thinking else sampling_class
    meta["num_ctx"] = options.get("num_ctx")
    meta["num_predict"] = options.get("num_predict")
    if options:
        body["options"] = options
    return meta


_THINK_BLOCK = re.compile(r"<think>([\s\S]*?)</think>", re.IGNORECASE)
_OPEN_THINK = re.compile(r"<think>([\s\S]*)$", re.IGNORECASE)


def split_reasoning(content: str) -> tuple[str, str]:
    """Separa o raciocínio que vazou no texto (`<think>…</think>`) da resposta.

    Args:
        content: texto devolvido pelo modelo.

    Returns:
        `(resposta, raciocínio)`. Um `<think>` sem fechamento (saída cortada no meio do
        raciocínio) vai inteiro para o raciocínio: a resposta fica vazia, que é a verdade.

    Observações:
        O Qwen3 escreve o bloco no texto quando o servidor não separa o canal de raciocínio
        (versões antigas do Ollama, ou modelos importados sem o modelo de template). Sem a
        separação, o bloco ia parar dentro de um arquivo gravado ou na resposta ao usuário.
    """
    if not content or "<think" not in content.lower():
        return content, ""
    thoughts = [m.group(1).strip() for m in _THINK_BLOCK.finditer(content)]
    rest = _THINK_BLOCK.sub("", content)
    open_match = _OPEN_THINK.search(rest)
    if open_match:
        thoughts.append(open_match.group(1).strip())
        rest = rest[: open_match.start()]
    return rest.strip(), "\n".join(t for t in thoughts if t)


_TOOL_CALL_BLOCK = re.compile(r"<tool_call>\s*([\s\S]*?)\s*</tool_call>", re.IGNORECASE)


def tool_calls_from_text(content: str, offered: set[str]) -> tuple[list[ToolCall], str]:
    """Recupera chamadas de ferramenta que o modelo escreveu no texto em vez do canal próprio.

    Args:
        content: texto devolvido pelo modelo.
        offered: nomes das ferramentas oferecidas nesta chamada.

    Returns:
        `(chamadas, texto restante)`. Só entram blocos `<tool_call>{json}</tool_call>` com JSON
        válido e nome de ferramenta oferecida; o resto do texto fica como estava.

    Observações:
        O Qwen3 usa esse formato no template; quando o analisador do servidor não reconhece o
        bloco (JSON com um detalhe fora do padrão, versão antiga), a chamada chegava como texto e
        o ciclo a tratava como resposta final — a etapa morria com um "JSON inválido".
    """
    if not content or not offered or "<tool_call>" not in content.lower():
        return [], content
    calls: list[ToolCall] = []
    kept: list[str] = []
    last = 0
    for match in _TOOL_CALL_BLOCK.finditer(content):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        name = data.get("name") or (data.get("function") or {}).get("name")
        if name not in offered:
            continue
        arguments = data.get("arguments")
        if arguments is None:
            arguments = data.get("parameters")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"raw": arguments}
        if not isinstance(arguments, dict):
            arguments = {}
        calls.append(ToolCall(id=f"text-{uuid.uuid4().hex[:8]}", name=name, arguments=arguments))
        kept.append(content[last : match.start()])
        last = match.end()
    if not calls:
        return [], content
    kept.append(content[last:])
    return calls, "".join(kept).strip()


def offered_tool_names(tools: list[dict[str, Any]] | None) -> set[str]:
    """Nomes das ferramentas oferecidas numa requisição (formato OpenAI)."""
    names: set[str] = set()
    for item in tools or []:
        function = (item or {}).get("function") or {}
        name = function.get("name") or (item or {}).get("name")
        if name:
            names.add(str(name))
    return names


def context_saturated(prompt_tokens: int | None, completion_tokens: int | None, num_ctx: int | None) -> bool:
    """A conversa ocupou a janela inteira (sinal de corte do prompt ou da resposta pelo servidor).

    Args:
        prompt_tokens: tokens de entrada que o servidor contou.
        completion_tokens: tokens de saída que o servidor contou.
        num_ctx: janela pedida.

    Returns:
        `True` quando entrada + saída chegam a 98 % da janela ou mais.
    """
    if not num_ctx or prompt_tokens is None:
        return False
    return (int(prompt_tokens) + int(completion_tokens or 0)) >= int(num_ctx * 0.98)
