# Documentos de progresso

O formato dos documentos que dizem onde o Callidus está e quanto falta.

Voltar ao [Hub](/docs/regras/README.md) · Documentos: [ROADMAP.md](/ROADMAP.md) · [docs/progresso/](/docs/progresso/README.md)

> **Revisado em:** 2026-10-21 · **Atualizado em:** 2026-10-21 · **Mudança:** major (criação)

**Regra:** quando uma entrega muda o estado do projeto, os documentos de progresso são atualizados **na mesma entrega** — não depois. O que não foi medido é marcado como *estimado*; na dúvida, erre para baixo.

## 📋 Quais são os documentos

| Documento | Pergunta que responde | Quem lê |
|-----------|----------------------|---------|
| [ROADMAP.md](/ROADMAP.md) | Em que estágio estamos, e quanto falta para o próximo? | Todos, primeiro |
| [gaps.md](/docs/progresso/gaps.md) | O que falta, ranqueado — **a fila de trabalho** | Agente sem tarefa dada |
| [roadmap.md](/docs/progresso/roadmap.md) | Portão do próximo estágio e marcos | Quem planeja |
| [avaliacao.md](/docs/progresso/avaliacao.md) | Nota por área, com evidência | Quem mede |
| [checklists/](/docs/progresso/checklists/README.md) | Itens esperados por dimensão | Quem fecha um gap |

O estado de **uma atividade** continua em [`internal/tarefas/`](/docs/regras/checklists-tarefas.md); o "onde parei" do agente local fica em `plan/STATUS.md` (fora do git). Os documentos de progresso falam do **projeto inteiro**.

## 🏷️ Linha de status

Logo abaixo do título e da frase de propósito de cada documento de progresso:

```markdown
> **Revisado em:** aaaa-mm-dd · **Atualizado em:** aaaa-mm-dd · **Mudança:** major|minor|patch (resumo)
```

- **Revisado em**: a última vez que alguém conferiu o documento contra a realidade, mesmo sem mudar nada.
- **Atualizado em**: a última vez que o conteúdo mudou.
- **Mudança**: `major` muda o estágio ou a ordem da fila; `minor` muda números ou itens; `patch` corrige texto.

## 🕑 Como registrar o histórico

No fim de cada documento, uma tabela com a mudança mais recente em cima:

```markdown
## 🕑 Histórico de revisão

| Data | Mudança | Resumo |
|------|---------|--------|
| 2026-10-21 | major | Criação |
```

## 📏 Medido ou estimado

Todo número leva o tipo:

| Tipo | Significa | Exemplo |
|------|-----------|---------|
| *medido* | saiu de um comando, teste ou avaliação, com data ou commit | 57 testes da interface passam (`node --test`, 2026-10-21) |
| *registrado* | foi medido por outro agente e anotado, mas não refeito agora | 892 testes Python passaram (checkpoint de 2026-10-21) |
| *estimado* | julgamento; sem medição | 8 h para ampliar a avaliação |

Avalie **comportamento**, não presença: um módulo que existe mas não foi exercitado não vale nota alta.

## 🪜 Estágios

| Estágio | Critério |
|---------|----------|
| pré-alpha | nenhum fluxo central funciona ponta a ponta |
| alpha | todo fluxo central passa no portão de [roadmap.md](/docs/progresso/roadmap.md) |
| beta | critérios de beta do mesmo documento — **decisão do dono** |
| 1.0 | critérios de lançamento — **decisão do dono** |

## ✅ O que atualizar em cada entrega

- [ ] [gaps.md](/docs/progresso/gaps.md): a entrada do gap (Faltando / Feito) e o rank, se mudou
- [ ] [avaliacao.md](/docs/progresso/avaliacao.md): nota, faltando, horas e evidência da área
- [ ] o checklist da dimensão em [checklists/](/docs/progresso/checklists/README.md)
- [ ] o marco em [roadmap.md](/docs/progresso/roadmap.md)
- [ ] [ROADMAP.md](/ROADMAP.md) se um número principal mudou, e a seção Status do [README](/README.md) igual a ele
- [ ] `plan/STATUS.md` (local)

## 🕑 Histórico de revisão

| Data | Mudança | Resumo |
|------|---------|--------|
| 2026-10-21 | major | Criação a partir do kit de agentes de IA |
