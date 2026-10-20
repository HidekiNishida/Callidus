# Catálogo de skills

O catálogo é a fonte das **skills** que o Callidus sabe aplicar: a pasta guarda o carregador
que lê o catálogo e monta o índice de competências disponível.

| Arquivo | Responsabilidade |
|---------|------------------|
| [`loader.py`](loader.py) | Carrega o catálogo, valida cada entrada e devolve as skills indexadas |

## 🧠 Como se liga ao resto

- O formato de cada skill (id, gatilho, prompt, ferramentas) é
  [`agent/skills/models.py`](../models.py).
- A **seleção** por contexto é [`agent/skills/selector.py`](../selector.py).
- A **descoberta** dos arquivos de skill no disco é [`agent/skills/discovery.py`](../discovery.py).
- A skill escolhida entra no prompt da operação como bloco de contexto.

Detalhe do funcionamento: [skills-estrategia.md](/docs/architecture/skills-estrategia.md).

**Voltar:** [skills/README.md](../README.md) · **Voltar:** [src/agent/README.md](../../README.md) · [Raiz](/README.md)