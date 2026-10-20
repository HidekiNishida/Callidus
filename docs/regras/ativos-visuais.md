# Padrões de Ativos Visuais

![Ativos visuais](/media/icons/ativos-visuais.svg){width=48}

Voltar ao [Hub](/docs/regras/README.md) · Documentação: [documentacao.md](/docs/regras/documentacao.md)

Ícones, imagens, diagramas e tabelas são parte do sistema de regras: aceleram leitura humana e parsing por agentes.

---

## Sumário

1. [Onde guardar](#onde-guardar)
2. [Catálogo de ícones atuais](#catálogo-de-ícones-atuais)
3. [Padrões de ícone SVG](#padrões-de-ícone-svg)
4. [Como embutir em Markdown](#como-embutir-em-markdown)
5. [Diagramas Mermaid](#diagramas-mermaid)
6. [Adaptação claro / escuro (obrigatória)](#adaptação-claro--escuro-obrigatória)
7. [Tabelas](#tabelas)
8. [Quando criar asset novo](#quando-criar-asset-novo)
9. [Checklist](#checklist)

---

## Onde guardar

| Tipo | Caminho | Formato preferido |
|------|---------|-------------------|
| Ícones de regras/guias | `/media/icons/` | SVG |
| Imagens de doc (screenshots, fotos) | `/media/` ou subpasta temática | PNG/WebP |
| Diagramas versionáveis | Mermaid **dentro** do `.md` | Mermaid |
| Export raster de diagrama (se necessário) | `/media/` | PNG |

Não coloque assets de documentação em `internal/` se forem referenciados por docs públicos.

---

## Catálogo de ícones atuais

### Conjunto de regras (identidade do hub)

| Arquivo | Uso |
|---------|-----|
| ![hub](/media/icons/hub.svg){width=24} `hub.svg` | Hub / índice |
| ![principios](/media/icons/principios.svg){width=24} `principios.svg` | Princípios |
| ![documentacao](/media/icons/documentacao.svg){width=24} `documentacao.svg` | Documentação |
| ![navegacao](/media/icons/navegacao.svg){width=24} `navegacao.svg` | Navegação de agentes |
| ![mcp](/media/icons/mcp.svg){width=24} `mcp.svg` | MCP / integrações |
| ![ativos](/media/icons/ativos-visuais.svg){width=24} `ativos-visuais.svg` | Ativos visuais |
| ![checklist](/media/icons/checklist.svg){width=24} `checklist.svg` | Checklists genéricos em docs |
| ![alerta](/media/icons/alerta.svg){width=24} `alerta.svg` | Avisos / anti-padrões |
| ![projeto](/media/icons/projeto.svg){width=24} `projeto.svg` | Contexto do projeto |
| ![organizacao](/media/icons/organizacao.svg){width=24} `organizacao.svg` | Organização de arquivos |
| ![validacoes](/media/icons/validacoes.svg){width=24} `validacoes.svg` | Validações e testes |
| ![auto](/media/icons/autoaperfeicoamento.svg){width=24} `autoaperfeicoamento.svg` | Autoaperfeiçoamento |
| ![commits](/media/icons/commits.svg){width=24} `commits.svg` | Commits automáticos |
| ![tarefas](/media/icons/tarefas.svg){width=24} `tarefas.svg` | Checklists de atividade |
| ![verificacao](/media/icons/verificacao.svg){width=24} `verificacao.svg` | Verificação final |

### Conjunto de categorias (identidade do documento)

Um ícone por **categoria de conteúdo**; o mesmo emoji marca a mesma categoria nas seções.
A tabela completa (emoji ↔ SVG ↔ significado) está em
[documentacao.md](/docs/regras/documentacao.md#marcadores-visuais).

| Arquivo | Categoria | Arquivo | Categoria |
|---------|-----------|---------|-----------|
| ![objetivo](/media/icons/objetivo.svg){width=24} `objetivo.svg` | Objetivo e propósito | ![referencias](/media/icons/referencias.svg){width=24} `referencias.svg` | Referências e materiais |
| ![conceitos](/media/icons/conceitos.svg){width=24} `conceitos.svg` | Conceitos e fundamentos | ![desenvolvimento](/media/icons/desenvolvimento.svg){width=24} `desenvolvimento.svg` | Desenvolvimento e manutenção |
| ![arquitetura](/media/icons/arquitetura.svg){width=24} `arquitetura.svg` | Arquitetura e estrutura | ![testes](/media/icons/testes.svg){width=24} `testes.svg` | Testes e validação |
| ![configuracao](/media/icons/configuracao.svg){width=24} `configuracao.svg` | Configuração e funcionamento | ![seguranca](/media/icons/seguranca.svg){width=24} `seguranca.svg` | Segurança e permissões |
| ![fluxos](/media/icons/fluxos.svg){width=24} `fluxos.svg` | Fluxos e processos | ![arquivos](/media/icons/arquivos.svg){width=24} `arquivos.svg` | Arquivos e diretórios |
| ![integracoes](/media/icons/integracoes.svg){width=24} `integracoes.svg` | Integrações e dependências | ![metricas](/media/icons/metricas.svg){width=24} `metricas.svg` | Métricas e observabilidade |
| ![restricoes](/media/icons/restricoes.svg){width=24} `restricoes.svg` | Restrições, riscos e cuidados | ![exemplos](/media/icons/exemplos.svg){width=24} `exemplos.svg` | Exemplos e recomendações |
| ![leitura](/media/icons/leitura.svg){width=24} `leitura.svg` | Navegação e leitura | — | — |

Caminho absoluto base: `/media/icons/`.

---

## Padrões de ícone SVG

| Propriedade | Padrão |
|-------------|--------|
| viewBox | `0 0 64 64` |
| Cantos | `rx="12"` no fundo |
| Estilo | Forma simples, alto contraste, sem texto no SVG |
| Acessibilidade | `role="img"` + `aria-label` |
| Nome | kebab-case alinhado ao tema (`mcp.svg`) |
| Paleta | Uma cor dominante por tema (evitar roxo genérico em tudo) |

Se faltar ícone: **criar SVG local** neste diretório (não depender de URL externa quebrável).

---

## Como embutir em Markdown

Cabeçalho de página (recomendado):

```markdown
![MCP](/media/icons/mcp.svg){width=48}
```

Inline em tabela:

```markdown
![Hub](/media/icons/hub.svg){width=28}
```

Avisos:

```markdown
![Alerta](/media/icons/alerta.svg){width=28} Texto do aviso.
```

Prefira caminhos absolutos do store para o Context resolver com estabilidade.

---

## Diagramas Mermaid

Use Mermaid para:

- Hierarquia de docs (flowchart)
- Protocolos passo a passo (flowchart)
- Decisões (flowchart com losango)

Evite:

- Diagramas com dezenas de nós sem agrupamento
- Substituir uma tabela simples de 3 linhas por um grafo
- Classes/cores fixas só legíveis em tema claro (ou só escuro)

Exemplo mínimo (**sem** cores hardcoded — o render usa o tema do ambiente):

```mermaid
flowchart LR
  Hub --> Filho
  Filho --> Asset
```

---

## Adaptação claro / escuro (obrigatória)

**Regra:** diagramas devem adaptar-se ao tema do browser ou ambiente (light/dark). Vale para docs no Context **e** para qualquer UI futura do projeto.

### Preferências

| Abordagem | Uso |
|-----------|-----|
| Mermaid **sem** `style` / `classDef` com hex fixo | **Preferido** em docs — herda cores do tema do viewer |
| SVG com `currentColor`, `fill="currentColor"` | Diagramas/ícones inline em HTML/UI |
| CSS variables (`var(--fg)`, `var(--border)`) | UI React/CSS do produto |
| Duas variantes light/dark | Só se o asset for raster (PNG) e inevitável |

### Proibido / evitar

| ❌ Evitar | Por quê |
|----------|---------|
| `style Nó fill:#fff,stroke:#000` no Mermaid | Quebra no dark (ou no light) |
| Texto cinza claro em fundo branco fixo | Some em um dos temas |
| PNG de diagrama só “modo claro” como única fonte | Prefira Mermaid versionável |
| Assumir fundo branco no Context | O ambiente do usuário pode ser escuro |

### Bom vs ruim (Mermaid)

| ❌ Ruim | ✅ Bom |
|---------|--------|
| `classDef box fill:#EEF,color:#111` | Sem classDef de cor; labels claros |
| `style A fill:#ffffff,color:#333333` | `flowchart` / `sequenceDiagram` padrão |
| Seta e nó com contraste só no light | Confiar no tema do Mermaid renderer |

### SVG / UI futura

```svg
<!-- Preferir herança de cor do texto/ambiente -->
<path d="..." fill="currentColor" stroke="currentColor"/>
```

Em CSS de produto:

```css
.diagram { color: var(--foreground); }
.diagram-edge { stroke: var(--border); }
@media (prefers-color-scheme: dark) {
  /* só se variáveis do design system não cobrirem */
}
```

Ícones decorativos do catálogo (com fundo colorido próprio) são **marcações de seção**, não diagramas de fluxo — para diagramas informativos, priorize Mermaid theme-aware ou SVG com `currentColor`.

### Checklist rápido de tema

- [ ] Mermaid sem fills/strokes hex desnecessários
- [ ] SVG de diagrama usa `currentColor` ou variáveis de tema
- [ ] Não dependo de PNG light-only como única representação
- [ ] Conferido na [verificação final](/docs/regras/verificacao-final.md)

---

## Tabelas

Tabelas são o default para:

- Mapas doc ↔ quando ler
- Comparações bom vs ruim
- Caminhos e convenções
- Sintoma → ação (como em MCP)

Cabeçalhos claros; uma ideia por célula; evite células com parágrafos longos (mova para seção).

---

## Quando criar asset novo

| Situação | Ação |
|----------|------|
| Nova página de regras | Criar ícone SVG correspondente + registrar neste catálogo |
| Screenshot de UI | Salvar em `media/` e linkar com alt text |
| Fluxo complexo | Preferir Mermaid no `.md`; export PNG só se o render falhar |
| Ícone duplicado com outro nome | Reutilizar o existente |

Atualize **este** arquivo e o [hub](/docs/regras/README.md) quando o catálogo mudar.

---

## Checklist

![Checklist](/media/icons/checklist.svg){width=32}

- [ ] Asset no path correto sob `media/`
- [ ] SVG com viewBox 64×64 e aria-label (ícones)
- [ ] Link absoluto no Markdown
- [ ] Alt text descritivo
- [ ] Catálogo atualizado se for ícone novo
- [ ] Diagramas adaptam a light/dark (sem cores fixas frágeis)
- [ ] Sem secrets / dados sensíveis em imagens

---

## Links cruzados

- [Hub](/docs/regras/README.md)
- [Princípios](/docs/regras/principios.md)
- [Documentação](/docs/regras/documentacao.md)
- [Navegação](/docs/regras/navegacao-agentes.md)
- [MCPs](/docs/regras/mcps.md)
- [Organização de arquivos](/docs/regras/organizacao-arquivos.md)
- [Validações e testes](/docs/regras/validacoes-testes.md)
- [Verificação final](/docs/regras/verificacao-final.md)
- [Contexto do projeto](/docs/project-context.md)
