# src/agent/i18n/locale.py — idioma do pedido e tradução de exibição
from __future__ import annotations

import re

_PT = ("não", "voce", "você", "crie", "criar", "adicione", "arquivo", "pasta", "isso", "fazer", "quero", "uma", "para", "com")
_EN = (
    "the", "and", "with", "please", "this", "that", "create", "add", "run", "write", "fix",
    "update", "tests", "unit", "for", "integrate", "logic", "into", "file", "implement",
)
_ES = ("el", "los", "las", "añade", "archivo", "prueba", "crear", "para", "con", "quiero", "una")

# Frases do orquestrador, escritas em português, e o equivalente na interface.
_FROM_PT: dict[str, dict[str, str]] = {
    "Planejando": {"en": "Planning", "es": "Planeando"},
    "Dividindo o trabalho": {"en": "Splitting the work", "es": "Dividiendo el trabajo"},
    "Pronta para executar": {"en": "Ready to run", "es": "Lista para ejecutar"},
    "Aguardando subtarefas": {"en": "Waiting for subtasks", "es": "Esperando subtareas"},
    "Liberada": {"en": "Released", "es": "Liberada"},
    "Nova tentativa": {"en": "Retrying", "es": "Nuevo intento"},
    "Resposta inválida": {"en": "Invalid reply", "es": "Respuesta inválida"},
    "Escrita falhou": {"en": "Write failed", "es": "La escritura falló"},
    "Ferramenta": {"en": "Tool", "es": "Herramienta"},
    "Verificado": {"en": "Verified", "es": "Verificado"},
    "Verificação falhou": {"en": "Verification failed", "es": "La verificación falló"},
    "Verificação inconclusiva": {"en": "Inconclusive verification", "es": "Verificación inconclusa"},
    "Concluída sem teste": {"en": "Finished without a test", "es": "Terminada sin prueba"},
    "Consolidando": {"en": "Consolidating", "es": "Consolidando"},
    "Bloqueada": {"en": "Blocked", "es": "Bloqueada"},
    "Loop detectado": {"en": "Loop detected", "es": "Bucle detectado"},
    "Limite de tentativas": {"en": "Attempt limit", "es": "Límite de intentos"},
    "Sem plano": {"en": "No plan", "es": "Sin plan"},
    "Sem instrução": {"en": "No instruction", "es": "Sin instrucción"},
    "Reabrindo": {"en": "Reopening", "es": "Reabriendo"},
    "Objetivo incompleto": {"en": "Objective incomplete", "es": "Objetivo incompleto"},
    "Resposta final": {"en": "Final answer", "es": "Respuesta final"},
    "Concluído": {"en": "Done", "es": "Concluido"},
    "Encerrado": {"en": "Closed", "es": "Cerrado"},
    "Aguardando": {"en": "Waiting", "es": "Esperando"},
    "Indo verificar": {"en": "Going to verify", "es": "Pasando a verificar"},
    "Escrevendo a resposta final.": {"en": "Writing the final answer.", "es": "Escribiendo la respuesta final."},
    "Pensando": {"en": "Thinking", "es": "Pensando"},
    "Pensou": {"en": "Thought", "es": "Pensó"},
    "Pensando…": {"en": "Thinking…", "es": "Pensando…"},
}

_TEMPLATES: list[tuple[re.Pattern[str], dict[str, str]]] = [
    (
        re.compile(r"^Pensando em como dividir «(.+)»\.$"),
        {
            "pt": "Pensando em como dividir «{0}».",
            "en": "Thinking about how to split “{0}”.",
            "es": "Pensando en cómo dividir «{0}».",
        },
    ),
    (
        re.compile(r"^Pensando na alteração «(.+)»\.$"),
        {
            "pt": "Pensando na alteração «{0}».",
            "en": "Thinking about the change “{0}”.",
            "es": "Pensando en el cambio «{0}».",
        },
    ),
    (
        re.compile(r"^Usando ([^\s]+)(?: em (.+))?\.$"),
        {
            "pt": "Usando {0}{1}.",
            "en": "Using {0}{1}.",
            "es": "Usando {0}{1}.",
        },
    ),
]

# (português, inglês, espanhol), do mais longo para o mais curto.
_GLOSSARY = [
    ("testes unitários", "unit tests", "pruebas unitarias"),
    ("lógica da calculadora", "calculator logic", "lógica de la calculadora"),
    ("resposta final", "final answer", "respuesta final"),
    ("subtarefas", "subtasks", "subtareas"),
    ("interface", "interface", "interfaz"),
    ("arquivo", "file", "archivo"),
    ("pasta", "folder", "carpeta"),
    ("testes", "tests", "pruebas"),
    ("teste", "test", "prueba"),
    ("criar", "create", "crear"),
    ("adicionar", "add", "añadir"),
    ("executar", "run", "ejecutar"),
    ("escrever", "write", "escribir"),
    ("corrigir", "fix", "corregir"),
    ("atualizar", "update", "actualizar"),
    ("implementar", "implement", "implementar"),
    ("verificar", "verify", "verificar"),
    ("listar", "list", "listar"),
    ("buscar", "search", "buscar"),
    ("editar", "edit", "editar"),
    ("apagar", "delete", "borrar"),
    ("testar", "test", "probar"),
    ("ler", "read", "leer"),
    ("esqueleto", "skeleton", "esqueleto"),
    ("lógica", "logic", "lógica"),
    ("para", "for", "para"),
    (" em ", " into ", " en "),
    (" em ", " to ", " en "),
]

_VERBS = {
    "en": {
        "pt": {
            "Create": "Criar",
            "Add": "Adicionar",
            "Run": "Executar",
            "Write": "Escrever",
            "Fix": "Corrigir",
            "Update": "Atualizar",
            "Implement": "Implementar",
            "Verify": "Verificar",
            "Read": "Ler",
            "List": "Listar",
            "Search": "Buscar",
            "Edit": "Editar",
            "Delete": "Apagar",
            "Test": "Testar",
            "Build": "Montar",
            "Make": "Fazer",
            "Integrate": "Integrar",
            "Connect": "Conectar",
            "Setup": "Configurar",
            "Refactor": "Refatorar",
        },
        "es": {
            "Create": "Crear",
            "Add": "Añadir",
            "Run": "Ejecutar",
            "Write": "Escribir",
            "Fix": "Corregir",
            "Update": "Actualizar",
            "Implement": "Implementar",
            "Verify": "Verificar",
            "Read": "Leer",
            "List": "Listar",
            "Search": "Buscar",
            "Edit": "Editar",
            "Delete": "Borrar",
            "Test": "Probar",
            "Build": "Armar",
            "Make": "Hacer",
            "Integrate": "Integrar",
            "Connect": "Conectar",
            "Setup": "Configurar",
            "Refactor": "Refactorizar",
        },
    }
}


def detect_language(text: str) -> str:
    """pt, en ou es. Sem pista clara, fica em português, idioma da interface."""
    sample = f" {(text or '').lower()} "
    if re.search(r"[ãõç]", sample):
        return "pt"
    if re.search(r"[ñ¿¡]", text or "") or ("ción" in sample and "ção" not in sample):
        return "es"
    scores = {
        "pt": sum(1 for word in _PT if f" {word} " in sample),
        "en": sum(1 for word in _EN if f" {word} " in sample),
        "es": sum(1 for word in _ES if f" {word} " in sample),
    }
    best = max(scores, key=lambda code: scores[code])
    if scores[best] == 0:
        return "pt"
    if scores["pt"] == scores["es"] and scores["pt"] >= scores["en"]:
        return "pt"
    return best


def language_instruction(code: str) -> str:
    return {
        "pt": "Escreva títulos, objetivos e a resposta final em português, o idioma do pedido.",
        "en": "Write titles, objectives and the final answer in English, the language of the request.",
        "es": "Escribe títulos, objetivos y la respuesta final en español, el idioma del pedido.",
    }.get(code, "Escreva títulos, objetivos e a resposta final em português, o idioma do pedido.")


def _apply_glossary(text: str, source: str, target: str) -> str:
    index = {"pt": 0, "en": 1, "es": 2}
    if source not in index or target not in index:
        return text
    out = text
    verbs = _VERBS.get(source, {}).get(target, {})
    for src, dst in verbs.items():
        out = re.sub(rf"^{re.escape(src)}\b", dst, out)
    pairs = sorted(
        ((row[index[source]], row[index[target]]) for row in _GLOSSARY),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
    for src, dst in pairs:
        if not src or src == dst:
            continue
        if " " in src:
            pattern = re.compile(re.escape(src), re.IGNORECASE)
        else:
            pattern = re.compile(rf"\b{re.escape(src)}\b", re.IGNORECASE)
        out = pattern.sub(dst, out)
    return out


def translate(text: str, target: str, *, _depth: int = 0) -> str:
    """Traduz pensamentos e títulos para o idioma do usuário. Identificadores ficam como estão."""
    code = target if target in {"pt", "en", "es"} else "pt"
    raw = (text or "").strip()
    if not raw or _depth > 3:
        return text
    if raw in _FROM_PT and code in _FROM_PT[raw]:
        if code == "pt":
            return text
        return _FROM_PT[raw][code]
    for pattern, forms in _TEMPLATES:
        match = pattern.match(raw)
        if not match:
            continue
        groups = list(match.groups())
        if pattern.pattern.startswith("^Usando"):
            tool = groups[0]
            where = f" em {groups[1]}" if groups[1] else ""
            if code == "en":
                where = f" on {groups[1]}" if groups[1] else ""
            if code == "es":
                where = f" en {groups[1]}" if groups[1] else ""
            return forms[code].format(tool, where)
        inner = [translate(group, code, _depth=_depth + 1) for group in groups]
        return forms[code].format(*inner)
    source = detect_language(raw)
    if source == code and not (code != "en" and re.match(r"^(Create|Add|Run|Write|Fix|Update|Implement|Integrate|Verify|Read|List|Search|Edit|Delete|Test|Build|Make)\b", raw)):
        return text
    if source == code:
        source = "en"
    return _apply_glossary(raw, source, code)
