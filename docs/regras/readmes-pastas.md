# README por pasta

![Organização](/media/icons/organizacao.svg){width=48}

Voltar ao [Hub](/docs/regras/README.md) · Organização: [organizacao-arquivos.md](/docs/regras/organizacao-arquivos.md)

## Regra (padrão do repositório)

**Toda pasta que contém código, scripts, testes ou documentação técnica deve ter um `README.md` local** servindo de índice: o que existe ali, para que serve, links para filhos e para o hub canônico.

| O README deve ter | Evitar |
|-------------------|--------|
| Título claro (H1) | Duplicar o hub inteiro de regras |
| 1–3 frases de propósito | Listar cada arquivo sem agrupar por responsabilidade |
| Tabela ou lista de **links relativos/absolutos** para filhos | Links quebrados |
| Link “voltar” para o pai ou [README raiz](/README.md) | Segredos ou paths de máquina efêmeros |

## Onde aplicar

| Área | Índice |
|------|--------|
| Código Python | [/src/README.md](/src/README.md) |
| Arquitetura | [/docs/architecture/README.md](/docs/architecture/README.md) |
| Docs gerais | [/docs/README.md](/docs/README.md) |
| Testes | [/tests/README.md](/tests/README.md) |
| UI | [/web/README.md](/web/README.md) |
| Scripts ops | [/scripts/README.md](/scripts/README.md) |
| Trabalho interno | [/internal/README.md](/internal/README.md) |

## Manutenção

Ao **criar pasta nova** com mais de um artefato ou módulo: adicionar/atualizar o `README.md` da pasta **no mesmo commit** que introduz a estrutura.

## Checklist

- [ ] README da pasta aponta para o pai
- [ ] Links usam caminhos `/…` na raiz do repo quando cruzam árvores
- [ ] Propósito alinhado ao que o código/docs realmente faz
