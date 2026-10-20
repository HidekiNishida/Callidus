# Marca do Callidus

![Organização](/media/icons/organizacao.svg){width=48}

**Regra:** o projeto se chama **Callidus**. Toda interface, documentação, metadado de API e mensagem de usuário usa o nome "Callidus" e o símbolo oficial. Termos genéricos em português ("o agente", "o runtime") continuam valendo como substantivo comum — não são nome de produto.

## 🎯 Identidade

| Peça | Arquivo | Uso |
|------|---------|-----|
| Símbolo | [`media/Callidus Logo.svg`](/media/Callidus%20Logo.svg) | "C" hexagonal com estrela azul ao centro |
| Nome | [`media/Callidus Name.svg`](/media/Callidus%20Name.svg) | Wordmark só com o nome |
| Nome + símbolo (horizontal) | [`media/Callidus Name + Logo Horizontal.svg`](/media/Callidus%20Name%20%2B%20Logo%20Horizontal.svg) | Cabeçalhos de README e da sidebar |
| Nome + símbolo (vertical) | [`media/Callidus Name + Logo Vertical.svg`](/media/Callidus%20Name%20%2B%20Logo%20Vertical.svg) | Cabeçalhos de docs |

Cores do símbolo: "C" em `#F6F4F4` (herda `currentColor` no SVG inline da UI), estrela em `#668DF7`.

Os arquivos em `media/` são a **fonte de verdade** da marca. As versões web em `web/static/assets/brand/` são geradas por [`scripts/build_brand_assets.py`](/scripts/build_brand_assets.py) — rode o script depois de trocar qualquer SVG em `media/`:

```bash
python scripts/build_brand_assets.py
```

| Gerado | Conteúdo |
|--------|----------|
| `callidus-mark.svg` | Só o símbolo, cor fixa (para `<img>`) |
| `callidus-mark-current.svg` | Só o símbolo com `currentColor` (para SVG inline) |
| `callidus-wordmark.svg` | Só o nome "CALLIDUS" |
| `callidus-lockup.svg` | Símbolo + nome, horizontal (sidebar) |
| `callidus-lockup-vertical.svg` | Símbolo + nome, vertical (docs) |
| `favicon.svg` | Símbolo sobre fundo escuro quadrado |

## ⚙️ Onde o nome aparece

| Camada | Onde |
|--------|------|
| Interface | `<title>`, favicon, lockup na sidebar, símbolo nas bolhas de chat, kicker do quadro ao vivo, estado vazio, nome nas mensagens do agente (pt/en/es) |
| API | `FastAPI(title=...)` e `description` — mostra em `/docs` (OpenAPI) |
| Pacote | `pyproject.toml`: `name = "callidus"`, script `callidus-api` |
| Runtime | `src/agent/brand.py` — constantes centralizadas (`BRAND_NAME`, `BRAND_TAGLINE`, caminhos) |
| Documentação | Títulos, `project-context.md` (campo "Nome do Project"), READMEs de pacote |

## 🎯 Renomeação de identificadores técnicos

Identificadores antigos continuam aceitos para não quebrar ambientes existentes:

| Antes | Agora | Compatibilidade |
|-------|-------|-----------------|
| pacote `agente-local` | `callidus` | — |
| script `agente-api` | `callidus-api` | `agente-api` segue como alias |
| `localStorage: agente-local-ui-v1` | `callidus-ui-v1` | A chave antiga é lida na primeira visita e apagada na primeira gravação |
| `.agente/anexos/<tarefa>/` | `.callidus/anexos/<tarefa>/` | A pasta legada continua em uso quando já tem arquivos da tarefa |
| `agente-inbox://local` | `callidus-inbox://local` | O prefixo legado ainda é reconhecido como inbox |
| `User-Agent: agente-local` | `callidus` | — |

Ao renomear qualquer identificador novo, registre a constante em `src/agent/brand.py` e documente aqui.

Voltar: [Regras — Hub](/docs/regras/README.md) · [Contexto do Projeto](/docs/project-context.md)