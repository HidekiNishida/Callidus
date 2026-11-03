# Engenharia de contexto

O que a organização acrescenta ao contexto de cada operação — e o que ela deliberadamente deixa de fora.

Voltar ao [hub de engenharia](/docs/engineering/README.md) · Montagem: [context-builder.md](/docs/architecture/context-builder.md) · Orçamento: [orcamento-contexto.md](/docs/architecture/orcamento-contexto.md)

## 📦 Pacote de contexto

O pacote de cada operação continua sendo montado por `OperationContextBuilder.build_for_task` com orçamento por componente: objetivo, requisitos que a etapa cobre, contrato, arquivos-alvo, resultados das dependências, skills selecionadas, memória e falhas anteriores.

A organização entra como **uma linha** no componente de contrato (`responsibility_line`):

```text
responsável: Desenvolvedor backend (Core Engineering); revisor: QA engineer; área protegida, coordenar com Arquiteto de software: src/agent/persistence/models.py
```

A linha tem menos de 400 caracteres (`tests/test_organization_api.py`, cenário I) e passa pelo mesmo orçamento: se o contrato for cortado, ela sai junto.

## 🚫 Fora do contexto

O catálogo organizacional, a matriz de papéis, o `resume.md` (inventário de auditoria, com centenas de milhares de caracteres) e o histórico de conversa não entram por padrão. O modelo recebe só o que a operação usa.
