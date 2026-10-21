# Estratégia linguística

Voltar ao [Hub da arquitetura](/docs/architecture/README.md) · Base: [provedores](/docs/architecture/provedores.md) · [orquestração](/docs/architecture/orquestracao-qualidade.md)

**O que é:** a separação entre o idioma do pedido, o idioma das instruções ao modelo e o idioma da interface.

**Por que:** um pedido em português não precisa ser reescrito para o usuário obter um plano. Em tarefa técnica, o modo automático pode mandar as instruções operacionais em inglês, com o pedido, os caminhos e as restrições intactos. Isso é uma hipótese de trabalho, não um resultado medido.

## Os três idiomas

| Papel | Onde vive | Exemplo |
|-------|-----------|---------|
| Entrada | `language.input_language` | português do pedido |
| Operacional | `language.operational_language` | inglês, só quando a estratégia aplicada for `english_operational` |
| Apresentação | `language.presentation_language` e `metadata.locale` | português da interface, do feed e da resposta final |

O contrato fica em `metadata.language` da raiz. A filha herda o mesmo recorte. O pedido original continua em `task.objective`.

## Modos

Configuração do processo: `language_mode` e `presentation_language` em `Settings`. A run pode substituir com `config.language_mode`, `config.presentation_language` e `config.language_profile.preferred`.

| Modo | Comportamento |
|------|----------------|
| `native` | Instruções e pedido no idioma original. Não há quadro em inglês. |
| `english_operational` | Quadro de instrução em inglês mais o pedido literal. Se a checagem de fidelidade falhar, volta ao pedido. |
| `auto` | Padrão. Inglês operacional em pedido técnico que não está em inglês. Prosa sem marca técnica, pedido já em inglês, ou perfil `preferred: native`, ficam no idioma original. |

`presentation_language=auto` usa o idioma detectado do pedido. Um valor `pt`, `en` ou `es` fixa a interface sem mudar o modo operacional.

Não há chamada de modelo para traduzir. O quadro é determinístico e entra no prompt de decomposição (`language_frame`) e no bloco de requisitos da operação. A resposta final continua obedecendo `language_instruction` do idioma de apresentação.

## Fidelidade

`fidelity_gaps` compara o candidato com o pedido. Caminho, URL, trecho entre crases, identificador em maiúsculas, número e frase de restrição (`não`, `nunca`, `sem alterar`, `do not`) precisam aparecer iguais. `apply_operational_text` devolve o original quando algo some. Ambiguidade com `ou` ou `talvez` fica registrada e não é resolvida pela estratégia.

## Recuperação

Uma saída `invalid_output` ou `empty_output` com inglês operacional troca a etapa para `native` uma vez (`switched_from`). A falha seguinte não alterna de volta. Outras causas não mudam o idioma: o diagnóstico continua o da falha, não o da língua.

## Como testar

```bash
python -m pytest tests/test_language_strategy.py -q
```

`compare_strategies` devolve só qual modo cada configuração aplica. Não mede acerto, token nem latência.

## Limites

Nenhum modelo local ou externo foi comparado nestes modos. Não há evidência de que o inglês operacional melhore planejamento, ferramenta ou verificação. O perfil por modelo só existe quando a configuração traz `language_profile.preferred`. O nome do modelo não escolhe a estratégia.
