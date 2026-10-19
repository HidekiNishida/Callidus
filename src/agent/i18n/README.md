# Internacionalização (`i18n/`) — Detecção de Idioma + Instrução no Prompt

Suporte a português, inglês e espanhol: detecção automática do idioma do objetivo e injeção de instrução no prompt.

## Módulos

| Arquivo | Exporta | Propósito |
|---------|---------|-----------|
| [`locale.py`](locale.py) | `detect_language(text)`, `language_instruction(locale)`, `translate(text, locale)` | **Idioma** — detecção heurística + instrução para o modelo + tradução simples de labels |

## Detecção (`detect_language`)

```python
# locale.py
def detect_language(text: str) -> str:
    """Heurística simples: conta palavras-chave por idioma."""
    text_lower = text.lower()
    pt_markers = {"o", "a", "de", "que", "e", "do", "da", "em", "um", "para", "com", "não", "uma", "os", "no", "se", "na", "por", "mais", "as", "dos", "como", "mas", "foi", "ele", "das", "tem", "à", "seu", "sua", "ou", "ser", "quando", "muito", "há", "nos", "já", "está", "eu", "também", "só", "pelo", "pela", "até", "isso", "ela", "entre", "depois", "sem", "mesmo", "aos", "ter", "seus", "quem", "nas", "me", "esse", "eles", "você", "tinha", "foram", "essa", "num", "nem", "suas", "meu", "às", "minha", "têm", "numa", "pelos", "elas", "havia", "seja", "qual", "será", "nós", "tenho", "lhe", "deles", "essas", "esses", "pelas", "este", "fosse", "dele", "tu", "te", "vocês", "vos", "lhes", "meus", "minhas", "teu", "tua", "teus", "tuas", "nosso", "nossa", "nossos", "nossas", "vosso", "vossa", "vossos", "vossas"}
    en_markers = {"the", "be", "to", "of", "and", "a", "in", "that", "have", "i", "it", "for", "not", "on", "with", "he", "as", "you", "do", "at", "this", "but", "his", "by", "from", "they", "we", "say", "her", "she", "or", "an", "will", "my", "one", "all", "would", "there", "their", "what", "so", "up", "out", "if", "about", "who", "get", "which", "go", "me"}
    es_markers = {"el", "la", "de", "que", "y", "en", "un", "ser", "se", "no", "haber", "por", "con", "su", "para", "como", "estar", "tener", "le", "lo", "todo", "pero", "más", "hacer", "o", "poder", "decir", "este", "ir", "otro", "ese", "si", "me", "ya", "ver", "porque", "dar", "cuando", "él", "muy", "sin", "vez", "mucho", "saber", "qué", "sobre", "mi", "alguno", "mismo", "yo", "también", "hasta", "año", "dos", "querer", "entre", "así", "primero", "desde", "grande", "ni", "nos", "llegar", "pasar", "tiempo", "ella", "sí", "día", "uno", "bien", "año", "poco"}
    
    pt_score = sum(1 for w in text_lower.split() if w in pt_markers)
    en_score = sum(1 for w in text_lower.split() if w in en_markers)
    es_score = sum(1 for w in text_lower.split() if w in es_markers)
    
    if pt_score >= en_score and pt_score >= es_score:
        return "pt"
    if en_score >= es_score:
        return "en"
    return "es"
```

## Instrução no Prompt (`language_instruction`)

```python
# locale.py
def language_instruction(locale: str) -> str:
    return {
        "pt": "Responda em português do Brasil.",
        "en": "Respond in English.",
        "es": "Responda en español.",
    }.get(locale, "Responda em português do Brasil.")
```

## Tradução de Labels (`translate`)

```python
# locale.py
def translate(text: str, locale: str) -> str:
    """Tradução simples de labels conhecidos (thoughts, actions, status)."""
    translations = {
        "pt": {...},
        "en": {...},
        "es": {...},
    }
    # Procura chaves conhecidas no texto e substitui
    # Usado em api/main.py → _thought_trace para traduzir phases/actions
```

## Uso no Código

### Orquestrador (início do run)
```python
# runner.py → _step_body
locale = (root_for_locale.metadata_json or {}).get("locale") or detect_language(root_for_locale.objective or "")
config = {**config, "locale": locale}
```

### Decomposição
```python
# decomposition.py → plan_with_model
prompt = f"{language_instruction(language)}\n{browser_line}\nObjetivo: {objective}..."
```

### Fechamento (resposta final)
```python
# closing.py → _write_final_answer
prompt = f"{language_instruction(str(config.get('locale') or 'pt'))}\n{capability_line(profile.model_id)}\n..."
```

### UI (api/main.py → _thought_trace)
```python
locale = locale_for_task(session, by_id.get(event.task_id))
text = translate(text, locale)
```

## Testes

```bash
pytest tests/test_conversations_memory_i18n.py -v
```

---

**Voltar:** [src/agent/README.md](../README.md) · **Raiz:** [README.md](../../../README.md)