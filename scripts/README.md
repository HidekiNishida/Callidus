# Scripts operacionais

Os scripts de manutenção e verificação do próprio projeto.

## 🧪 Verificação

Verificações leves, reproduzíveis e sem infraestrutura nova. Rode-as ao mexer em
documentação ou em código — elas são a barreira mecânica das regras de
[documentação](/docs/regras/documentacao.md).

| Script | O que garante |
|--------|----------------|
| [check_docs.py](/scripts/check_docs.py) | Nenhum link interno ou âncora quebrada na documentação |
| [check_references.py](/scripts/check_references.py) | Nenhum arquivo ou símbolo citado que não exista no código |
| [check_markdown.py](/scripts/check_markdown.py) | Estrutura do Markdown: H1, hierarquia, tabelas, blocos de código, diagramas Mermaid |
| [check_code_drift.py](/scripts/check_code_drift.py) | Nenhuma edição "de documentação" alterou o código (AST sem docstrings contra o Git) |
| [check_imports.py](/scripts/check_imports.py) | Nenhuma importação ou definição se perdeu numa refatoração (separa "movido" de "perdido") |
| [padronizar_cabecalhos.py](/scripts/padronizar_cabecalhos.py) | Aplica o cabeçalho padrão nos módulos Python sem tocar no código |

```bash
source .venv/bin/activate
python scripts/check_docs.py && python scripts/check_references.py && python scripts/check_markdown.py
```

## 🛠️ Manutenção

| Script | Função |
|--------|--------|
| [resume.py](/scripts/resume.py) | Verifica/carimba o [`resume.md`](/resume.md) contra a estrutura do código ([regra](/docs/regras/resumo-projeto.md)) |
| [backup-data.sh](/scripts/backup-data.sh) | Tar.gz de `data/` em `backups/` |
| [build_brand_assets.py](/scripts/build_brand_assets.py) | Gera os assets web da marca Callidus em `web/static/assets/brand/` a partir de `media/` |
| [fix-python314-editable.py](/scripts/fix-python314-editable.py) | Corrige `import agent` no Python 3.14 |

## 📊 Medição

| Script | Função |
|--------|--------|
| [medir-hierarquia.py](/scripts/medir-hierarquia.py) | **Mede as consultas sob demanda** — caracteres levados ao pai, inferências gastas e concorrência máxima do executor (`--json`) |
| [avaliar-consultas.py](/scripts/avaliar-consultas.py) | **Avalia o casamento lexical** com gabarito (direta/indireta/ambígua/sem evidência + adversariais) |
| [medir-ollama.py](/scripts/medir-ollama.py) | **Mede com Ollama real** — latência, chamadas, contexto, RSS do servidor e VRAM |

**Voltar:** [README](/README.md) · [Regras](/docs/regras/README.md)