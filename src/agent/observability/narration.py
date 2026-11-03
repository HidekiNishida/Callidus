"""
Arquivo: src/agent/observability/narration.py
Nome: narration.py
Propósito: transformar a saída pública do modelo, fragmento a fragmento, em narração do agente na linha do tempo.
Responsabilidade: camada de aplicação — filtro incremental do texto público e emissão de `agent.narration.*`.
Componentes: NarrationFilter, NarrationStream, NARRATION_PERSIST_CHARS, narrates, describe_tool_calls.
Dependências: agent.observability.emitter (emit), agent.observability.batching (DeltaBatcher).
Observações: nada aqui chama o modelo. A narração é o texto que o próprio modelo escreveu para
a pessoa; raciocínio (`<think>`), chamadas de ferramenta escritas no texto e cargas JSON/código
nunca viram narração. Só o início e o fim são gravados no banco; os fragmentos são efêmeros.
Quando o modelo pede ferramentas sem escrever nada público (o raciocínio fica no canal privado),
a narração descreve a ação a partir da própria chamada — um fato, nunca um resultado.
"""
from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable

from agent.observability.batching import DeltaBatcher
from agent.observability.emitter import emit

# Teto do texto gravado no fim de uma narração. Narração é prosa curta; um texto maior que isso
# é a entrega da etapa escrita em prosa, e o que importa dela já está na resposta do modelo.
NARRATION_PERSIST_CHARS = 8_000

# Finalidades cuja saída é a resposta ao usuário: ela já aparece como resposta da conversa,
# e repeti-la como narração duplicaria o texto na tela.
_SILENT_PURPOSES = frozenset({"final_answer", "agent_query"})

_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"
# Formas em que modelos locais escrevem a chamada de ferramenta no texto (Qwen3 usa as duas
# primeiras; `<|` abre token especial de template). Qualquer uma encerra a narração.
_TOOL_OPENS = ("<tool_call>", "<function-call>", "<function_call>", "<|")
_FENCE = "```"
# Começo de linha com cara de tag: `<nome`, `</nome`, `<|...`. Prosa não abre linha assim.
_LINE_TAG = re.compile(r"<[/|A-Za-z_][^<>\s]*")
_TAG_WAIT = 40


# Verbo de cada ferramenta comum na frase de reserva; as demais aparecem pelo nome.
_TOOL_VERBS = {
    "read_file": "Vou ler",
    "write_file": "Vou gravar",
    "edit_file": "Vou editar",
    "delete_file": "Vou apagar",
    "make_dir": "Vou criar a pasta",
    "move_file": "Vou mover",
    "list_dir": "Vou listar",
    "glob_files": "Vou procurar arquivos com",
    "search_grep": "Vou buscar",
    "run_command": "Vou executar",
    "run_pytest": "Vou rodar os testes",
    "run_script": "Vou executar o script",
    "git_status": "Vou conferir o estado do Git",
    "git_diff": "Vou ver as diferenças no Git",
    "browser": "Vou usar o navegador",
}
# Argumento que identifica o alvo da ação, na ordem de preferência.
_TARGET_KEYS = ("path", "pattern", "command", "url", "query", "from")
_TARGET_CHARS = 80


def _call_target(arguments: object) -> str:
    """Alvo curto de uma chamada (caminho, padrão, comando, URL), ou vazio.

    Args:
        arguments: argumentos já decodificados da chamada.

    Returns:
        O alvo entre crases, truncado; vazio quando a chamada não tem alvo legível.
    """
    if not isinstance(arguments, dict):
        return ""
    for key in _TARGET_KEYS:
        value = arguments.get(key)
        if isinstance(value, list):
            value = " ".join(str(v) for v in value)
        if isinstance(value, str) and value.strip():
            text = " ".join(value.split())
            if len(text) > _TARGET_CHARS:
                text = text[: _TARGET_CHARS - 1] + "…"
            return f"`{text}`"
    return ""


def describe_tool_calls(calls: list[dict] | None) -> str:
    """Frase de narração para uma resposta que só pediu ferramentas.

    Args:
        calls: chamadas pedidas pelo modelo (`name`, `arguments`).

    Returns:
        Uma frase por chamada (até três), ou vazio sem chamadas.

    Observações:
        Descreve a ação pedida, nunca o resultado: a ferramenta ainda não rodou.
    """
    sentences: list[str] = []
    for call in calls or []:
        if not isinstance(call, dict) or not call.get("name"):
            continue
        name = str(call["name"])
        target = _call_target(call.get("arguments"))
        verb = _TOOL_VERBS.get(name)
        if verb:
            sentence = f"{verb} {target}".strip() if target else verb
        else:
            sentence = f"Vou usar `{name}`" + (f" em {target}" if target else "")
        sentences.append(sentence + ".")
    if len(sentences) > 3:
        sentences = sentences[:3] + [f"E mais {len(sentences) - 3} ação(ões)."]
    return " ".join(sentences)


def narrates(purpose: str | None) -> bool:
    """Diz se a saída de uma chamada com esta finalidade pode virar narração.

    Args:
        purpose: finalidade da chamada ao modelo.

    Returns:
        `False` para a resposta final ao usuário; `True` para o resto.
    """
    return (purpose or "") not in _SILENT_PURPOSES


class NarrationFilter:
    """Separa, sem esperar o fim da resposta, o texto que é fala para a pessoa.

    Regras, aplicadas incrementalmente:

    - `<think>…</think>` é raciocínio: descartado, mesmo quando a tag chega partida em dois fragmentos;
    - `<tool_call>`, `<function-call>` e afins encerram a narração: o que vem depois é chamada de
      ferramenta escrita no texto;
    - uma linha que começa com `{`, `[`, ```` ``` ```` ou com uma tag (`<nome>`) é carga (JSON da
      operação, código, marcação de template) e encerra a narração dessa resposta.

    Só fica retido o mínimo para decidir (o começo de uma linha até o primeiro caractere visível,
    ou um `<` que pode ser o início de uma tag); o resto sai na hora em que chegou.
    """

    def __init__(self) -> None:
        """Começa no início de uma linha, fora de raciocínio, sem nada retido."""
        self._pending = ""
        self._mode = "text"  # text | think | payload
        self._line_start = True
        self.public_chars = 0

    @property
    def closed(self) -> bool:
        """Verdadeiro quando a resposta já virou carga: nada mais vira narração."""
        return self._mode == "payload"

    def feed(self, piece: str) -> str:
        """Recebe um fragmento do modelo e devolve a parte que é narração.

        Args:
            piece: fragmento exatamente como o provedor entregou.

        Returns:
            O texto público pronto para exibir (pode ser vazio).
        """
        if self._mode == "payload" or not piece:
            return ""
        buf = self._pending + piece
        self._pending = ""
        out: list[str] = []
        while buf:
            if self._mode == "payload":
                return self._count(out)
            if self._mode == "think":
                end = buf.lower().find(_THINK_CLOSE)
                if end < 0:
                    # Guarda só a cauda que pode ser o começo de `</think>`.
                    self._pending = buf[-(len(_THINK_CLOSE) - 1):]
                    return self._count(out)
                buf = buf[end + len(_THINK_CLOSE):]
                self._mode = "text"
                # Depois do raciocínio, o texto recomeça como uma linha nova (sem o espaço de sobra).
                self._line_start = True
                continue
            if self._line_start:
                stripped = buf.lstrip(" \t\r\n")
                if not stripped:
                    # Só espaço até agora: a linha ainda não disse o que é.
                    if self.public_chars or any(out):
                        out.append(buf)
                    return self._count(out)
                lead = buf[: len(buf) - len(stripped)]
                first = stripped[0]
                if first in "{[":
                    self._mode = "payload"
                    return self._count(out)
                if first == "`" and len(stripped) < len(_FENCE):
                    self._pending = buf
                    return self._count(out)
                if stripped.startswith(_FENCE):
                    self._mode = "payload"
                    return self._count(out)
                if first == "<" and not stripped.lower().startswith(_THINK_OPEN):
                    tag = _LINE_TAG.match(stripped)
                    if tag is not None and tag.end() == len(stripped) and len(stripped) < _TAG_WAIT:
                        # A tag ainda não terminou de chegar: decide no próximo fragmento.
                        self._pending = buf
                        return self._count(out)
                    if tag is not None and stripped[tag.end():tag.end() + 1] in (">", " ", "="):
                        self._mode = "payload"
                        return self._count(out)
                if self.public_chars or any(out):
                    out.append(lead)
                buf = stripped
                self._line_start = False
            cut = min((i for i in (buf.find("<"), buf.find("\n")) if i >= 0), default=-1)
            if cut < 0:
                out.append(buf)
                break
            if buf[cut] == "\n":
                out.append(buf[: cut + 1])
                buf = buf[cut + 1:]
                self._line_start = True
                continue
            out.append(buf[:cut])
            rest = buf[cut:]
            low = rest.lower()
            if low.startswith(_THINK_OPEN):
                self._mode = "think"
                buf = rest[len(_THINK_OPEN):]
                continue
            if low.startswith(_TOOL_OPENS):
                self._mode = "payload"
                return self._count(out)
            if _THINK_OPEN.startswith(low) or any(opener.startswith(low) for opener in _TOOL_OPENS):
                # `<` no fim do fragmento: pode ser uma tag partida; espera o próximo.
                self._pending = rest
                return self._count(out)
            out.append("<")
            buf = rest[1:]
        return self._count(out)

    def _count(self, out: list[str]) -> str:
        """Junta a saída e soma o que já foi publicado.

        Args:
            out: pedaços públicos desta chamada.

        Returns:
            O texto junto.
        """
        text = "".join(out)
        self.public_chars += len(text)
        return text


class NarrationStream:
    """Uma narração: nasce no primeiro texto público e termina com a resposta (ou a falha).

    Eventos:

    - `agent.narration.started` (gravado): identidade, chamada de origem e etapa;
    - `agent.narration.delta` (efêmero): só o trecho novo e o deslocamento acumulado;
    - `agent.narration.completed` (gravado): o texto inteiro e o estado
      (`completed`, `interrupted` ou `failed`).

    Sem texto público, nenhum evento sai: uma narração vazia não é inventada.
    """

    def __init__(
        self,
        output_id: str,
        *,
        purpose: str = "",
        streamed: bool = True,
        interval_ms: int | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Prepara a narração de uma chamada ao modelo.

        Args:
            output_id: chamada ao modelo de onde vem o texto.
            purpose: finalidade da chamada.
            streamed: o texto chega em fragmentos reais do provedor (`False`: chega inteiro no fim).
            interval_ms: intervalo de agrupamento dos fragmentos; o padrão vem da configuração.
            clock: relógio monotônico (injetável em teste).
        """
        self.narration_id = uuid.uuid4().hex[:12]
        self.output_id = output_id
        self.purpose = purpose
        self.streamed = streamed
        self._filter = NarrationFilter()
        self._clock = clock
        self._parts: list[str] = []
        self._offset = 0
        self._started_at: float | None = None
        self._first_at: float | None = None
        self._done = False
        self._source = "model"
        self._batcher = DeltaBatcher(self._publish, interval_ms=interval_ms)

    @property
    def started(self) -> bool:
        """Verdadeiro depois do primeiro texto público."""
        return self._started_at is not None

    @property
    def text(self) -> str:
        """Texto público acumulado até agora."""
        return "".join(self._parts)

    def feed(self, piece: str) -> None:
        """Recebe um fragmento do provedor e publica o que for narração.

        Args:
            piece: fragmento exatamente como chegou.
        """
        if self._done:
            return
        public = self._filter.feed(piece)
        if not public:
            return
        if self._started_at is None:
            self._started_at = self._clock()
            emit(
                "agent.narration.started",
                {
                    "narration_id": self.narration_id,
                    "output_id": self.output_id,
                    "purpose": self.purpose,
                    "streamed": self.streamed,
                },
                commit=True,
            )
        self._parts.append(public)
        self._batcher.add(public)

    def _publish(self, text: str) -> None:
        """Publica um lote de texto novo com o deslocamento acumulado.

        Args:
            text: trecho novo, já filtrado.
        """
        if self._first_at is None:
            self._first_at = self._clock()
        emit(
            "agent.narration.delta",
            {"narration_id": self.narration_id, "output_id": self.output_id, "text": text, "offset": self._offset},
        )
        self._offset += len(text)

    def finish(self, status: str = "completed", *, error: str = "", fallback: str = "") -> None:
        """Fecha a narração, gravando o texto recebido e o estado.

        Args:
            status: `completed`, `interrupted` (cancelamento) ou `failed`.
            error: motivo curto da falha, quando houver.
            fallback: frase usada só quando o modelo não escreveu nada público
                (ex.: `describe_tool_calls`); marcada no evento como `source: tool_calls`.

        Observações:
            Idempotente. O texto parcial de uma geração interrompida é preservado.
        """
        if self._done:
            return
        if self._started_at is None and fallback.strip():
            # A reserva não passa pelo filtro: ela é montada por nós e começa com crase.
            self._source = "tool_calls"
            self._started_at = self._clock()
            emit(
                "agent.narration.started",
                {
                    "narration_id": self.narration_id,
                    "output_id": self.output_id,
                    "purpose": self.purpose,
                    "streamed": False,
                    "source": self._source,
                },
                commit=True,
            )
            self._parts.append(fallback.strip())
            self._batcher.add(fallback.strip())
        self._done = True
        self._batcher.flush()
        if self._started_at is None:
            return
        text = self.text.strip()
        payload: dict[str, object] = {
            "narration_id": self.narration_id,
            "output_id": self.output_id,
            "content": text[:NARRATION_PERSIST_CHARS],
            "status": status,
            "chars": len(text),
            "truncated": len(text) > NARRATION_PERSIST_CHARS,
            "duration_ms": int((self._clock() - self._started_at) * 1000),
            "source": self._source,
        }
        if error:
            payload["error"] = error[:300]
        emit("agent.narration.completed", payload)
        self._parts.clear()
