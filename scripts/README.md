# Scripts operacionais

| Script | Função |
|--------|--------|
| [backup-data.sh](/scripts/backup-data.sh) | Tar.gz de `data/` em `backups/` |
| [build_brand_assets.py](/scripts/build_brand_assets.py) | Gera os assets web da marca Callidus em `web/static/assets/brand/` a partir de `media/` |
| [fix-python314-editable.py](/scripts/fix-python314-editable.py) | Corrige `import agent` no Python 3.14 |
| [resume.py](/scripts/resume.py) | Verifica/carimba o [`resume.md`](/resume.md) contra a estrutura do código ([regra](/docs/regras/resumo-projeto.md)) |
| [medir-hierarquia.py](/scripts/medir-hierarquia.py) | **Mede as consultas sob demanda** — caracteres levados ao pai, inferências gastas e concorrência máxima do executor (`--json`) |
| [avaliar-consultas.py](/scripts/avaliar-consultas.py) | **Avalia o casamento lexical** com gabarito (direta/indireta/ambígua/sem evidência + adversariais) |
| [medir-ollama.py](/scripts/medir-ollama.py) | **Mede com Ollama real** — latência, chamadas, contexto, RSS do servidor e VRAM |

Voltar: [README](/README.md)
