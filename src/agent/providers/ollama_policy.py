"""
Arquivo: src/agent/providers/ollama_policy.py
Nome: ollama_policy.py
Propósito: adaptar a requisição e a resposta do Ollama à família do modelo (janela, saída, amostragem, formato).
Responsabilidade: camada de infraestrutura — política por família de modelo do adaptador Ollama; nenhuma regra de negócio.
Componentes: ModelFamily, family_for, thinking_only, prefill_empty_thinking, repetition_cut, purpose_class, apply_request_policy, split_reasoning, tool_calls_from_text, context_saturated.
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

Variantes **só de raciocínio** do Qwen3 (`qwen3-vl:8b`, que é a `8b-thinking`, e toda tag com
`thinking`) ignoram `think: false`: raciocinam sempre. Tratá-las como modo direto cortava a saída
no meio do raciocínio (medido: plano com 2 048 tokens de raciocínio e conteúdo vazio, 96 s, duas
vezes seguidas). Com `think: false`, o adaptador entrega a essas variantes um bloco de raciocínio
**vazio já preenchido** (`<think></think>` no começo da resposta): o modelo responde direto.
Medido com o `qwen3-vl:8b` no Ollama 0.40.3: um plano curto caiu de milhares de tokens de
raciocínio (≈170 s, quase sempre cortado) para 53 tokens. Com `think: true` na configuração,
o raciocínio fica e recebe a reserva na saída, com a amostragem do Modelfile.
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
# Saída mínima garantida para código: reescrever um arquivo de ~100 linhas (em JSON) passa de
# 2 000 tokens. Visto com o qwen3-vl:8b: prompt de ~5 600 numa janela de 8 192 deixava 2 574 e a
# reescrita do main.py voltava cortada.
_CODE_OUTPUT = 4096


@dataclass(frozen=True)
class ModelFamily:
    """O que o adaptador sabe de uma família de modelos servida pelo Ollama.

    Atributos:
        name: rótulo da família (aparece nos metadados da inferência).
        manage_window: a política define `num_ctx` e `num_predict` quando a configuração não define.
        sampling: amostragem padrão por classe de finalidade (`structured`, `code`, `prose`).
        thinking_sampling: amostragem quando o raciocínio está ligado.
        always_thinks: o modelo raciocina mesmo com `think: false` (variante só de raciocínio).
    """

    name: str
    manage_window: bool = True
    sampling: dict[str, dict[str, Any]] = field(default_factory=dict)
    thinking_sampling: dict[str, Any] = field(default_factory=dict)
    always_thinks: bool = False


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
# Variante só de raciocínio. Sem raciocínio (bloco vazio preenchido), vale a amostragem do modo
# direto; com raciocínio pedido na configuração, a do Modelfile (a de raciocínio do fabricante).
_QWEN3_THINKING = ModelFamily(name="qwen3_thinking", sampling=_QWEN3.sampling, always_thinks=True)
# Começo de resposta com o raciocínio já encerrado: a variante só de raciocínio responde direto.
EMPTY_THINK = "<think>\n\n</think>\n\n"
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
        return _QWEN3_THINKING if thinking_only(low) else _QWEN3
    return _GENERIC


def prefill_empty_thinking(body: dict[str, Any]) -> bool:
    """Acrescenta o bloco de raciocínio vazio quando a variante só de raciocínio não deve raciocinar.

    Args:
        body: corpo `/api/chat` já com `model`, `messages` e `think`.

    Returns:
        Verdadeiro quando o bloco foi acrescentado (última mensagem = assistente com `EMPTY_THINK`,
        que o Ollama continua). Nada muda com `think: true`, para outras famílias ou quando a
        conversa já termina numa mensagem do assistente.
    """
    if body.get("think") or not family_for(str(body.get("model") or "")).always_thinks:
        return False
    messages = body.get("messages") or []
    if not messages or messages[-1].get("role") == "assistant":
        return False
    messages.append({"role": "assistant", "content": EMPTY_THINK})
    return True


def _prefilled(body: dict[str, Any]) -> bool:
    """Diz se o corpo termina no bloco de raciocínio vazio (o modelo não vai raciocinar)."""
    messages = body.get("messages") or []
    return bool(messages) and messages[-1].get("role") == "assistant" and messages[-1].get("content") == EMPTY_THINK


def thinking_only(model_id: str) -> bool:
    """Diz se a tag é uma variante só de raciocínio do Qwen3.

    Args:
        model_id: nome do modelo no Ollama.

    Returns:
        Verdadeiro para tags com `thinking` e para o `qwen3-vl` sem `instruct` (no Ollama,
        `qwen3-vl:8b` e `qwen3-vl:latest` apontam para a variante `thinking`).
    """
    low = (model_id or "").lower()
    if "instruct" in low:
        return False
    return "thinking" in low or "qwen3-vl" in low


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
    thinking = bool(body.get("think")) or (family.always_thinks and not _prefilled(body))
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
            if sampling_class == "code" and configured <= 0:
                needed = max(needed, prompt + _CODE_OUTPUT + allowance + _WINDOW_MARGIN)
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
    defaults = family.thinking_sampling if thinking else family.sampling.get(sampling_class or "", {})
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
    if not content or not offered:
        return [], content
    if "<tool_call>" not in content.lower():
        return _bare_tool_calls(content, offered)
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
        return _bare_tool_calls(content, offered)
    kept.append(content[last:])
    return calls, "".join(kept).strip()


def _as_call(data: Any, offered: set[str]) -> ToolCall | None:
    """Converte `{"name": ..., "arguments": {...}}` em chamada, se o nome for de ferramenta oferecida."""
    if not isinstance(data, dict):
        return None
    name = data.get("name") or (data.get("function") or {}).get("name")
    if name not in offered:
        return None
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
    return ToolCall(id=f"text-{uuid.uuid4().hex[:8]}", name=name, arguments=arguments)


def _bare_tool_calls(content: str, offered: set[str]) -> tuple[list[ToolCall], str]:
    """Chamadas escritas como objetos JSON soltos, um após o outro (sem `<tool_call>`).

    É o formato do `qwen3-vl:8b` quando responde sem raciocínio (bloco vazio pré-preenchido):
    `{"name": "read_file", "arguments": {...}}` em linhas seguidas. Antes, o texto ia para o
    leitor de JSON único e a etapa falhava com "Extra data" ou "faltam campos: path".

    Args:
        content: texto devolvido pelo modelo.
        offered: nomes das ferramentas oferecidas.

    Returns:
        `(chamadas, texto restante)`. Só objetos com nome de ferramenta oferecida viram chamada;
        o resto (outro JSON, prosa, um objeto final cortado) fica no texto.
    """
    decoder = json.JSONDecoder()
    calls: list[ToolCall] = []
    kept: list[str] = []
    pos = 0
    while pos < len(content):
        start = content.find("{", pos)
        if start < 0:
            break
        try:
            data, end = decoder.raw_decode(content, start)
        except json.JSONDecodeError:
            break
        call = _as_call(data, offered)
        if call is None:
            kept.append(content[pos:end])
        else:
            kept.append(content[pos:start])
            calls.append(call)
        pos = end
    if not calls:
        return [], content
    kept.append(content[pos:])
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


# Repetição sem fim: o mesmo bloco de até 8 linhas repetido 3 vezes seguidas no fim da resposta.
_REPEAT_TIMES = 3
_REPEAT_MAX_BLOCK = 8
_REPEAT_MIN_CHARS = 40


def repetition_cut(text: str) -> str | None:
    """Detecta a repetição sem fim no fim do texto e devolve o texto com uma única cópia do bloco.

    Visto com o `qwen3-vl:8b` respondendo direto: a mesma sequência de chamadas
    (`read_file a.py`, `read_file b.py`, `write_file ...`) repetida até o limite de saída — uma
    chamada levou 833 s. Cortar na terceira cópia economiza o resto e preserva o conteúdo útil.

    Args:
        text: texto recebido até agora (só linhas completas contam).

    Returns:
        O texto até o fim da primeira cópia do bloco repetido, ou `None` sem repetição.
    """
    if text.count("\n") < _REPEAT_TIMES:
        return _periodic_cut(text)
    lines = text.split("\n")[:-1]  # a última linha pode estar incompleta
    lines = [line for line in lines if line.strip()]
    for size in range(1, _REPEAT_MAX_BLOCK + 1):
        span = size * _REPEAT_TIMES
        if len(lines) < span:
            break
        tail = lines[-span:]
        block = tail[:size]
        if sum(len(line) for line in block) < _REPEAT_MIN_CHARS:
            continue
        if all(tail[i * size:(i + 1) * size] == block for i in range(_REPEAT_TIMES)):
            keep = len(lines) - span + size
            kept_lines = lines[:keep]
            # Reconstroi pelo texto original para não mexer em espaços e quebras.
            pos = 0
            for line in kept_lines:
                pos = text.index(line, pos) + len(line)
            return text[:pos]
    return _periodic_cut(text)


# Repetição dentro de uma linha só: em JSON as quebras do código viram "\\n" escapado, e um
# `new_string` que se repete sem fim nunca chega a uma linha nova (visto: 7 585 tokens, 278 s).
_PERIOD_PROBE = 120
_PERIOD_WINDOW = 6000
_PERIOD_MIN = 60


def _periodic_cut(text: str) -> str | None:
    """Detecta o fim do texto repetindo o mesmo trecho 3 vezes seguidas, com ou sem quebra de linha.

    Args:
        text: texto recebido até agora.

    Returns:
        O texto até o fim da primeira das 3 cópias, ou `None` sem repetição.
    """
    if len(text) < 3 * _PERIOD_MIN:
        return None
    probe = text[-_PERIOD_PROBE:] if len(text) >= _PERIOD_PROBE * 3 else text[-_PERIOD_MIN:]
    window_start = max(0, len(text) - _PERIOD_WINDOW)
    end = len(text) - len(probe)
    pos = text.rfind(probe, window_start, end + len(probe) - 1)
    while pos >= window_start:
        period = len(text) - len(probe) - pos
        if period >= _PERIOD_MIN and 3 * period <= len(text):
            a, b, c = text[-3 * period : -2 * period], text[-2 * period : -period], text[-period:]
            if a == b == c:
                return text[: len(text) - 2 * period]
        pos = text.rfind(probe, window_start, pos + len(probe) - 1)
    return None
