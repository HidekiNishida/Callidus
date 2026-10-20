# Regras do Callidus — Hub de Entrada

**Comece sempre aqui.** Este hub é o ponto de entrada obrigatório para humanos e agentes de IA que trabalham no Project **Callidus**.

Leia este índice, escolha apenas os ramos necessários à tarefa e siga os links. Não carregue a árvore inteira por padrão — veja [Navegação para agentes](/docs/regras/navegacao-agentes.md).

---

## Sumário (TOC)

1. [Propósito deste conjunto](#propósito-deste-conjunto)
2. [Mapa da documentação](#mapa-da-documentação)
3. [Ordem de leitura recomendada](#ordem-de-leitura-recomendada)
4. [Checklist rápido antes de qualquer tarefa](#checklist-rápido-antes-de-qualquer-tarefa)
5. [Fluxo visual](#fluxo-visual)
6. [Convenções de caminho](#convenções-de-caminho)
7. [Manutenção deste hub](#manutenção-deste-hub)

---

## Propósito deste conjunto

Estas regras definem **como** o agente deve documentar e trabalhar:

| Regra-mãe | Significado prático |
|-----------|---------------------|
| Documentar tudo | Toda decisão, fluxo e artefato relevante vira doc hierárquico e linkado |
| Navegação seletiva | Agentes leem o hub e só os ramos necessários |
| Estilo didático | Docs claros para humanos **e** IAs (exemplos, tabelas, checklists) |
| Ativos visuais | Ícones, diagramas e tabelas aceleram compreensão; diagramas adaptam light/dark |
| Marca | O projeto é **Callidus**: nome, símbolo e aliases legados seguem [marca.md](/docs/regras/marca.md) |
| Continuidade MCP | MCP ausente/quebrado → obter/autenticar/reparar **antes** de seguir |
| Organização hierárquica | Pastas/arquivos com responsabilidade única e nomes claros (eficiência de tokens) |
| Validações e testes | Cobertura proporcional nas dimensões aplicáveis (segurança, limites, stress, etc.) |
| Autoaperfeiçoamento | Mudança relevante → atualizar docs/regras/checklists do próprio agente |
| Commits automáticos | Toda mudança commitada pelo agente (PT); vigora quando houver git |
| Estado da tarefa | Checklist em `internal/tarefas/` para avançar e retomar |
| Verificação final | Antes de fechar: consistência código ↔ docs ↔ checklists ↔ regras |
| Código | [AGENTS.md](/AGENTS.md) — fonte **canônica** de como escrever e manter código (cabeçalho, docstrings, SOLID, testes, documentação) |

Contexto estável do projeto: [project-context.md](/docs/project-context.md).

---

## Mapa da documentação

| Ícone | Documento | Quando ler |
|-------|-----------|------------|
| <img src="/media/icons/principios.svg" width="20" alt="Princípios"> | [principios.md](/docs/regras/principios.md) | Sempre na primeira sessão; ao duvidar de prioridade |
| <img src="/media/icons/documentacao.svg" width="20" alt="Documentação"> | [documentacao.md](/docs/regras/documentacao.md) | Ao criar, editar ou reorganizar docs |
| <img src="/media/icons/navegacao.svg" width="20" alt="Navegação"> | [navegacao-agentes.md](/docs/regras/navegacao-agentes.md) | No início de toda tarefa (como atravessar a árvore) |
| <img src="/media/icons/mcp.svg" width="20" alt="MCP"> | [mcps.md](/docs/regras/mcps.md) | Quando a tarefa depende de MCP ou ferramentas externas |
| <img src="/media/icons/ativos-visuais.svg" width="20" alt="Ativos"> | [ativos-visuais.md](/docs/regras/ativos-visuais.md) | Ao adicionar ícones, imagens, diagramas ou tabelas visuais |
| <img src="/media/icons/organizacao.svg" width="20" alt="Organização"> | [organizacao-arquivos.md](/docs/regras/organizacao-arquivos.md) | Ao criar pastas, nomear arquivos ou separar temas |
| <img src="/media/icons/organizacao.svg" width="20" alt="Organização"> | [readmes-pastas.md](/docs/regras/readmes-pastas.md) | Ao criar pasta de código/docs — **README.md** índice |
| <img src="/media/icons/organizacao.svg" width="20" alt="Marca"> | [marca.md](/docs/regras/marca.md) | Ao criar/alterar nome, símbolo, logo ou textos de marca na interface e nos docs |
| <img src="/media/icons/validacoes.svg" width="20" alt="Validações"> | [validacoes-testes.md](/docs/regras/validacoes-testes.md) | Ao criar/alterar qualquer artefato que precise verificação |
| <img src="/media/icons/autoaperfeicoamento.svg" width="20" alt="Autoaperfeiçoamento"> | [autoaperfeicoamento.md](/docs/regras/autoaperfeicoamento.md) | Quando a mudança influencia trabalho futuro / regras |
| <img src="/media/icons/commits.svg" width="20" alt="Commits"> | [commits.md](/docs/regras/commits.md) | Ao fechar mudança em repo git (ou para saber o que fazer sem repo) |
| <img src="/media/icons/tarefas.svg" width="20" alt="Tarefas"> | [checklists-tarefas.md](/docs/regras/checklists-tarefas.md) | **Toda** atividade: criar/atualizar estado e retomar |
| <img src="/media/icons/verificacao.svg" width="20" alt="Verificação"> | [verificacao-final.md](/docs/regras/verificacao-final.md) | **Antes de encerrar** qualquer tarefa |
| <img src="/media/icons/documentacao.svg" width="20" alt="Documentação"> | [resumo-projeto.md](/docs/regras/resumo-projeto.md) | **Toda** tarefa que altera o repo: manter o [`resume.md`](/resume.md) em dia |
| <img src="/media/icons/organizacao.svg" width="20" alt="Organização"> | [AGENTS.md](/AGENTS.md) | **Fonte canônica** das regras de engenharia — cabeçalho, docstrings, camadas, SOLID, testes, documentação e sincronização |

Template de checklist: [`internal/tarefas/_modelo-checklist.md`](/internal/tarefas/_modelo-checklist.md).

```mermaid
flowchart TD
  Hub["docs/regras/README.md<br/>HUB"]
  Ctx["docs/project-context.md"]
  P["principios.md"]
  D["documentacao.md"]
  N["navegacao-agentes.md"]
  M["mcps.md"]
  A["ativos-visuais.md"]
  O["organizacao-arquivos.md"]
  V["validacoes-testes.md"]
  S["autoaperfeicoamento.md"]
  C["commits.md"]
  T["checklists-tarefas.md"]
  F["verificacao-final.md"]

  Ctx --> Hub
  Hub --> P
  Hub --> D
  Hub --> N
  Hub --> M
  Hub --> A
  Hub --> O
  Hub --> V
  Hub --> S
  Hub --> C
  Hub --> T
  Hub --> F
  P -.-> D
  D -.-> A
  D -.-> O
  N -.-> M
  N -.-> T
  V -.-> C
  V -.-> F
  S -.-> V
  T -.-> S
  T -.-> F
```

---

## Ordem de leitura recomendada

### Primeira vez no projeto

1. [project-context.md](/docs/project-context.md) — metas e restrições
2. Este hub
3. [AGENTS.md](/AGENTS.md) — regras de engenharia (cabeçalho, docstrings, arquitetura, testes)
4. [principios.md](/docs/regras/principios.md)
5. [navegacao-agentes.md](/docs/regras/navegacao-agentes.md)
6. [checklists-tarefas.md](/docs/regras/checklists-tarefas.md) — criar estado da atividade

### Por tipo de tarefa

| Tipo de tarefa | Ramos obrigatórios | Ramos sob demanda |
|----------------|--------------------|-------------------|
| Qualquer atividade | navegação + checklists-tarefas | verificação-final no fechamento |
| Escrever/atualizar docs | princípios + documentação | organização, ativos-visuais |
| Reorganizar pastas/nomes | organização + documentação | navegação |
| Implementar feature/código | navegação + princípios + validações | mcps, commits, documentação, verificação-final |
| Integrar ferramenta externa | navegação + mcps | documentação, validações |
| Fechar / encerrar tarefa | verificação-final + checklists-tarefas | commits, autoaperfeiçoamento |
| Fechar mudança em git | commits + validações + verificação-final | autoaperfeiçoamento |
| Mudança que afeta o futuro | autoaperfeiçoamento | hub (manutenção) |
| Revisar/manter assets | ativos-visuais (incl. tema light/dark) | documentação |

---

## Checklist rápido antes de qualquer tarefa

- [ ] Li o hub e identifiquei os ramos necessários
- [ ] Criei/abri checklist em [`internal/tarefas/`](/docs/regras/checklists-tarefas.md) (copiar o [modelo](/internal/tarefas/_modelo-checklist.md))
- [ ] Consultei [project-context.md](/docs/project-context.md) se a tarefa toca escopo/metas
- [ ] Verifiquei se preciso de MCP; se sim, apliquei [mcps.md](/docs/regras/mcps.md) **antes** de continuar
- [ ] Planejei onde documentar o resultado (pasta + links; ver [organizacao-arquivos.md](/docs/regras/organizacao-arquivos.md))
- [ ] Planejei validações/testes e dimensões aplicáveis ([validacoes-testes.md](/docs/regras/validacoes-testes.md))
- [ ] Diagramas/visuais: adaptação light/dark ([ativos-visuais.md](/docs/regras/ativos-visuais.md))
- [ ] Ao mudar regras/convenções: [autoaperfeicoamento.md](/docs/regras/autoaperfeicoamento.md)
- [ ] Antes de encerrar: [verificacao-final.md](/docs/regras/verificacao-final.md) (código ↔ docs ↔ checklists ↔ regras)
- [ ] Ao final: commit se houver git ([commits.md](/docs/regras/commits.md))
- [ ] Não editei `notes.md` / `preferences.md` (coordenador) salvo autorização explícita

---

## Fluxo visual

```mermaid
flowchart LR
  Start([Nova tarefa]) --> Hub[Ler hub]
  Hub --> CL[Criar/abrir checklist]
  CL --> Select[Selecionar ramos]
  Select --> MCP{MCP necessário?}
  MCP -->|Sim| Fix[Detectar / auth / reparar]
  MCP -->|Não| Work[Executar + marcar etapas]
  Fix --> Work
  Work --> Val[Validar dimensões aplicáveis]
  Val --> Self{Impacta futuro?}
  Self -->|Sim| Up[Atualizar regras/docs]
  Self -->|Não| Final[Verificação final]
  Up --> Final
  Final --> Git{Há git?}
  Git -->|Sim| Commit[Commit PT]
  Git -->|Não| Doc[Documentar no store]
  Commit --> Done([Concluído])
  Doc --> Done
```

---

## Convenções de caminho

| Tipo | Raiz | Uso |
|------|------|-----|
| Docs para o usuário/agente | `/docs/` | Regras, contexto, guias |
| Mídia e ícones | `/media/` | SVG, PNG, diagramas exportados |
| Trabalho interno | `/internal/` | Evidências, rascunhos, auditorias |
| Estado de atividades | `/internal/tarefas/` | Checklists `- [ ]` / `- [x]` por tarefa |
| Status/preferências | `notes.md`, `preferences.md` | **Somente coordenador** |

Em links Markdown deste conjunto, prefira **caminhos absolutos do store** (ex.: `/docs/regras/principios.md`) para o Cursor Context resolver de forma estável.

---

## Manutenção deste hub

Quando adicionar um novo documento de regras:

1. Crie o arquivo sob `/docs/regras/`
2. Adicione linha na [tabela do mapa](#mapa-da-documentação)
3. Atualize o diagrama Mermaid se a hierarquia mudar
4. Cross-linke a partir dos irmãos relevantes
5. Atualize [ativos-visuais.md](/docs/regras/ativos-visuais.md) se houver ícone novo
6. Se a mudança for estrutural, siga [autoaperfeicoamento.md](/docs/regras/autoaperfeicoamento.md)

<img src="/media/icons/alerta.svg" width="20" alt="Alerta"> **Não** publique regras finais só em `internal/` — regras vigentes moram em `docs/`.

---

## Links cruzados

- [Princípios](/docs/regras/principios.md)
- [Documentação](/docs/regras/documentacao.md)
- [Navegação para agentes](/docs/regras/navegacao-agentes.md)
- [MCPs](/docs/regras/mcps.md)
- [Ativos visuais](/docs/regras/ativos-visuais.md)
- [Organização de arquivos](/docs/regras/organizacao-arquivos.md)
- [Validações e testes](/docs/regras/validacoes-testes.md)
- [Autoaperfeiçoamento](/docs/regras/autoaperfeicoamento.md)
- [Commits](/docs/regras/commits.md)
- [Checklists de tarefas](/docs/regras/checklists-tarefas.md)
- [Verificação final](/docs/regras/verificacao-final.md)
- [Modelo de checklist](/internal/tarefas/_modelo-checklist.md)
- [Contexto do projeto](/docs/project-context.md)
- [Regras de engenharia (canônicas)](/AGENTS.md)