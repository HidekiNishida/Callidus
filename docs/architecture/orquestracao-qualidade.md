# Qualidade, decomposição seletiva e feed

Voltar ao [Hub da arquitetura](/docs/architecture/README.md) · Base: [skills-estrategia.md](/docs/architecture/skills-estrategia.md) · [requisitos](/docs/architecture/requisitos-verificacao-progresso.md)

**O que é:** três peças no ciclo que já existia. O contrato de qualidade diz o que o pedido pede e o que é piso profissional. A disposição escolhe executar, investigar, decompor ou replanejar quando uma etapa foi marcada para subdividir. O feed publica a frase dessa decisão, sem uma inferência a mais.

**Por que:** a estratégia já classificava o domínio, mas misturava pedido, suposição e critério. O atomizador dividia de novo uma etapa que já tinha um resultado só. O feed dizia "Pensando" mesmo quando a decisão já estava tomada.

## Contrato de qualidade

`build_quality_contract()` roda no primeiro passo da raiz, depois da estratégia, e grava em `task_contracts.acceptance_json.quality`. Os requisitos `R1…` que já estavam no aceite permanecem.

| Campo | Origem |
|-------|--------|
| `explicit` | texto do usuário |
| `inferred` | perfil do domínio (engenharia, depuração, documentação, verificação, interface, consulta) |
| `premises` | suposições da estratégia, marcadas como premissa |
| `constraints` | somente leitura, proteção de testes, teto de protótipo |
| `exclusions` | o que não entra, inclusive endurecimento quando o pedido é protótipo |
| `uncertainties` | tensão do próprio texto, como pedir mudança e proibir alteração |
| `acceptance` | critérios com método e estado `pendente` |

A filha recebe `inherit_quality()`: restrições, exclusões e os critérios que conversam com o objetivo local. O prompt da operação mostra esse recorte e rotula premissa como não confirmada. Não há chamada de modelo nesta camada.

Pedido com "protótipo", "mvp" ou "experimento" usa o teto `prototype`: um critério de demonstração e a exclusão de produção.

## Disposição

`decide_disposition()` é determinística. O planejador da raiz (`resolve_decomposition_plan`) continua responsável pelo primeiro plano — pergunta curta, automação e o demo `e2e` seguem os atalhos que já tinham.

A decisão **substitui o atomizador** quando a etapa tem `atomize` e ainda não gastou duas tentativas:

| Ação | Quando | Efeito |
|------|--------|--------|
| `execute` | a etapa já é um passo, a profundidade de proteção estourou, ou o objetivo é um resultado só | vira operação, com `atomize` desligado |
| `investigate` | o texto não localiza o ponto da mudança | plano com `list_dir`, depois a ação, e verificação se houver mudança |
| `decompose` | três ou mais itens, ou objetivo longo e complexo | `adaptive_decompose_operation` |
| `replan` | já existe falha e a etapa gastou duas tentativas | não divide de novo; segue como operação para a abordagem registrada |

Depois de duas tentativas, a divisão adaptativa antiga permanece: é o caminho de recuperação, não uma árvore nova por estilo.

## Feed

O evento `work.explained` carrega `category` (`activity`, `decision`, `result`, `alert`, `error`), `text` e `phase`. O texto passa pela mesma redação de segredos dos outros eventos. A interface mostra essa frase na atividade da conversa e na linha do tempo do detalhe.

A narração não chama o modelo. Se montar o evento falhar, o passo do orquestrador continua. O feed não calcula porcentagem nem anuncia verificação que não rodou: o critério nasce com estado `pendente`.

## Como testar

```bash
python -m pytest tests/test_quality_disposition.py tests/test_progress_metrics.py::test_simple_question_is_not_over_decomposed tests/test_functional_depth.py -q
node --test tests/web/work-explained.test.mjs
```

## Limites

A comparação com o modelo local, medindo tokens e taxa de acerto antes e depois, não foi executada nesta mudança. O procedimento é o de [avaliacao.md](/docs/architecture/avaliacao.md), com os cenários simples, vagos e de investigação, no mesmo provedor e nos mesmos limites. A disposição não reescreve o plano da raiz; uma raiz longa sem `atomize` ainda passa pelo planejador existente.
