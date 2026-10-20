# Checklist: Rebrand — Agente de IA Local → Callidus

| Campo | Valor |
|-------|-------|
| Estado | concluída |
| Criado em | 2026-10-19 |
| Atualizado em | 2026-10-19 |
| Agente / tarefa | Rebrand completo: nome, símbolo, interface, documentação e identificadores técnicos |
| Regras consultadas | [Hub](/docs/regras/README.md), [marca.md](/docs/regras/marca.md), [principios.md](/docs/regras/principios.md), [documentacao.md](/docs/regras/documentacao.md), [organizacao-arquivos.md](/docs/regras/organizacao-arquivos.md), [valiacoes-testes.md](/docs/regras/validacoes-testes.md), [verificacao-final.md](/docs/regras/verificacao-final.md) |

## 🎯 Objetivo

Trocar o nome do produto para **Callidus**, aplicando o símbolo novo na interface (sidebar, favicon, bolhas de chat, estado vazio, quadro ao vivo) e em toda a documentação, mantendo compatibilidade com os identificadores técnicos antigos (`agente-api`, `agente-local-ui-v1`, `.agente/anexos/`, `agente-inbox://`) para não quebrar ambientes existentes.

## Próxima ação

Nenhuma — tarefa concluída. Evolução futura sugerida: permitir escolha de tema (light/dark) com o símbolo adaptado.

## 🔄 Etapas

- [x] Gerar assets web a partir dos SVGs de `media/` (símbolo, wordmark, favicon) em `web/static/assets/brand/`
- [x] Verificar renderização dos assets com `rsvg-convert`
- [x] Interface: `<title>`, `<meta description>`, favicon, wordmark na sidebar, símbolo nas bolhas de chat e no estado vazio, kicker do quadro ao vivo
- [x] CSS: `.brand-lockup`, `.brand-mark`, `.brand-mark-img`, `.brand-mark-lg`
- [x] `app.js`: `BRAND_NAME`, `brandMark()`, rótulos pt/en/es, `localStorage` com fallback para a chave legada
- [x] Criar `src/agent/brand.py` com as constantes centralizadas
- [x] Renomear identificadores com alias: pacote `callidus`, scripts `callidus-api` + `agente-api`, `User-Agent`, `FastAPI(title)`, `.callidus/anexos/` com fallback para `.agente/anexos/`, inbox `callidus-inbox://`
- [x] Atualizar `scripts/fix-python314-editable.py` (`.pth` novo + remoção do legado)
- [x] Documentação: README raiz, `docs/`, `skills/`, `src/`, `internal/`, `notes.md`, `preferences.md`
- [x] Criar `docs/regras/marca.md` e linkar no hub
- [x] Renomear a pasta do repositório para `~/Documents/Projetos/Callidus` e ajustar caminhos absolutos
- [x] Validar: suíte de testes, import dos módulos tocados, carregamento da UI

## Bloqueios

- Nenhum no momento.

## Artefatos

| Path absoluto | Notas |
|---------------|-------|
| `/web/static/assets/brand/` | `callidus-mark.svg`, `callidus-mark-current.svg`, `callidus-wordmark.svg`, `callidus-wordmark-vertical.svg`, `favicon.svg` |
| `/src/agent/brand.py` | Constantes de marca e aliases legados |
| `/docs/regras/marca.md` | Regra de marca e tabela de compatibilidade |
| `/docs/architecture/frontend.md` | Seção "Identidade visual (Callidus)" |
| `/media/Callidus *.svg` | Fonte de verdade da marca (CorelDRAW) |
| `/scripts/build_brand_assets.py` | Gera `web/static/assets/brand/` a partir de `media/` |
| `/tests/test_brand.py` | 8 testes: nome, aliases legados, anexos, assets em disco |

## Notas de retomada

Os SVGs de `media/` vieram do CorelDRAW com `viewBox` em unidades de centésimos de milímetro e cores em classes CSS (`.fil0` = `#F6F4F4`, `.fil1` = `#668DF7`). Os glifos do nome vêm misturados entre `<path>` e `<polygon>` — a extração precisa cobrir os dois, senão as letras "L", "L" e "I" somem do wordmark.

As versões em `web/static/assets/brand/` são reescritas com `viewBox` limpo. `callidus-mark.svg` usa cor fixa (para `<img>`, a interface é dark-only) e `callidus-mark-current.svg` usa `currentColor` (para o SVG inline em `app.js`).

Identificadores legados que continuam aceitos: `agente-api` (alias do script), `agente-local-ui-v1` (localStorage, lido uma vez e apagado na primeira gravação), `.agente/anexos/<tarefa>/` (usada quando já tem arquivos da tarefa), `agente-inbox://` (prefixo ainda reconhecido como inbox), `agente-local-src.pth` (removido pelo script de fix do Python 3.14).

Depois de renomear a pasta do repositório, o `.venv` precisa ser reapontado: os scripts em `.venv/bin/` guardam o caminho absoluto no shebang e o `.pth` aponta para `src/`. Rode `sed` para trocar o caminho antigo em `.venv/bin/*` e `.venv/pyvenv.cfg`, ajuste o `.pth` e rode `python scripts/fix-python314-editable.py` (o `pip install -e` recria um `.pth` com prefixo `_`, que o Python 3.14 ignora).

No macOS, um agente externo reaplica a flag `UF_HIDDEN` nos arquivos de `site-packages` dentro de ~1s, e o Python 3.14 também pula `.pth` ocultos. Por isso o script cria um link simbólico `site-packages/agent` → `src/agent`: o importador do Python ignora a flag, e o nome do alvo não começa com `_`.