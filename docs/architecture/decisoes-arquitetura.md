# Decisões de arquitetura (ADR)

![Projeto](/media/icons/projeto.svg){width=48}

Registro das decisões estruturais do Callidus: **contexto, problema, alternativas, decisão,
consequências e estado**. O resumo curto está em
[visao-geral.md](/docs/architecture/visao-geral.md#decisões-adr-resumido).

| ADR | Tema | Estado |
|-----|------|--------|
| [ADR-001](#adr-001-ciclo-e-execução-em-pacotes-diferentes) | Ciclo e execução em pacotes diferentes | Aceito |
| [ADR-002](#adr-002-api-como-fachada-de-roteadores-por-assunto) | API como fachada de roteadores por assunto | Aceito |
| [ADR-003](#adr-003-verificação-independente-de-quem-executa) | Verificação independente de quem executa | Aceito |
| [ADR-004](#adr-004-o-sqlite-como-fonte-da-verdade) | O SQLite como fonte da verdade | Aceito |
| [ADR-005](#adr-005-o-modelo-como-peça-substituível) | O modelo como peça substituível | Aceito |

---

## ADR-001: Ciclo e execução em pacotes diferentes

**Status:** Aceito · **Data:** 2026-10

### Contexto

`orchestrator/runner.py` cresceu até ~2150 linhas e passou a concentrationar dois problemas
diferentes:

1. **o ciclo do run** — escolher a próxima tarefa, planejar, detectar estagnação, pausar,
   retomar, consolidar, aceitar globalmente;
2. **a execução de uma tarefa** — montar o contexto, chamar o modelo, aplicar a alteração,
   recusar escritas indevidas, rodar a verificação, gravar a evidência.

O método `_execute_task` sozinho tinha ~640 linhas, com regras de escrita duplicadas em três
trechos (caminho da ferramenta, protocolo JSON e recusa) e um bloco de código inalcançável
depois de um `return`.

### Problema

Dois problemas com ritmos de mudança diferentes conviviam no mesmo arquivo. Uma mudança no
protocolo do modelo exigia ler o ciclo inteiro; uma mudança no ciclo (limites, pausa) exigia
ler o protocolo do modelo. O arquivo virava ponto central: todo mundo dependia dele.

### Alternativas

| Alternativa | Por que não |
|-------------|-------------|
| Só quebrar `_execute_task` em métodos menores | Mantém tudo na mesma classe; a dependência continua sendo o arquivo inteiro |
| Criar uma interface `TaskExecutor` e várias implementações | Há **uma** forma de executar uma tarefa; a abstração seria artificial |
| Mover o fluxo inteiro para o executor | O ciclo (planejamento, estagnação, pausa) não é execução de tarefa — voltaria ao mesmo arquivo |

### Decisão

Separar por **papel**, não por quantidade de métodos:

- `orchestrator/runner.py` — o **ciclo** (quando rodar o quê).
- `orchestrator/execution/` — a **execução** de uma tarefa (como):
  - `executor.py` — `TaskExecutor`: despacho da etapa e verificação;
  - `model_operation.py` — `ModelOperation`: fluxo da operação de modelo;
  - `runtime.py` — `ExecutionRuntime`: colaboradores e a fábrica de provedor;
  - `providers.py`, `guards.py`, `tool_results.py`, `writes.py`, `journal.py`, `workspace.py`
    — regras puras e helpers com dono claro.

O executor recebe um `ExecutionRuntime`; o provedor continua injetável pelo mesmo ponto de
injeção de antes (`runner._select_provider`), preservando os testes que injetam um provedor.

### Consequências

- **Prós**: `runner.py` caiu de ~2150 para ~1000 linhas; o pacote `execution/` tem um README
  próprio; a duplicação das regras de escrita foi removida (rejeitadas em `writes.py`); o bloco
  inalcançável desapareceu.
- **Contras**: um pacote a mais no caminho da chamada; o executor precisa dos colaboradores
  (session, settings, services, tools) — resolvido com o `ExecutionRuntime`.
- **Neutro**: nenhum contrato observável mudou — endpoints, eventos, estados, evidências e
  persistência seguem iguais.

---

## ADR-002: API como fachada de roteadores por assunto

**Status:** Aceito · **Data:** 2026-10

### Contexto

`api/main.py` tinha ~1300 linhas com 66 rotas de cinco assuntos diferentes (sistema,
projetos, conversas, tarefas, execuções) mais a montagem da aplicação e da SPA.

### Problema

Procurar "onde está a rota que altera o status da tarefa" exigia varrer um arquivo único.
Rotas de leitura (tarefa, conversa) repetiam a montagem do payload em pontos diferentes.

### Alternativas

| Alternativa | Por que não |
|-------------|-------------|
| Só mover funções para arquivos auxiliares | A rota continuaria no `main.py`; a leitura do fluxo não melhoraria |
| Um router por método HTTP | Não corresponde ao assunto; espalha a mesma função por vários arquivos |
| Service layer por trás de cada rota | O projeto **já** tem services; a rota já delega — o problema é a organização, não a lógica |

### Decisão

`api/main.py` vira **fachada**: cria a aplicação, inclui os roteadores e monta a SPA.
Cada assunto ganha um módulo com `APIRouter`:

`system_routes.py` · `project_routes.py` · `conversation_routes.py` · `task_routes.py` ·
`run_routes.py` · (já existentes) `agent_routes.py` · `automation_routes.py` ·
`provider_routes.py` · `observe_routes.py`

A apresentação de leitura foi extraída para `presenters.py` (`present_task`,
`present_conversation`) e a visão ao vivo para `live_view.py` (linha do tempo de pensamentos
e o texto legível das ações).

### Consequências

- **Prós**: cada arquivo tem um assunto; a ordem de inclusão dos roteadores define a
  precedência das rotas; a apresentação de leitura tem um único dono.
- **Contras**: um import a mais para quem procura uma rota.
- **Neutro**: as 66 rotas, os caminhos, os códigos HTTP e o formato do payload não mudaram
  (verificado pelo OpenAPI: 81 paths antes e depois).

---

## ADR-003: Verificação independente de quem executa

**Status:** Aceito (mantido) · **Data:** 2026-10

### Contexto

O modelo propõe a alteração; o mesmo processo a aplica no disco.

### Decisão

Quem escreve **não** aprova o próprio resultado. A verificação é um passo separado
(`TaskExecutor.finalize_verification`), roda um verificador determinístico e grava
`EvidenceModel`. A resposta final é a exceção já registrada: ela não altera a medição, e o
rodapé determinístico da resposta reporta o veredito.

### Consequências

O `runner` não pode "aprovar" uma etapa por atalho. Mudar isso exige mudar o ciclo de
verificação inteiro, não uma rota.

---

## ADR-004: O SQLite como fonte da verdade

**Status:** Aceito (mantido) · **Data:** 2026-10

### Decisão

O estado do run, das tarefas, das tentativas e das evidências vive no SQLite. A conversa com
o modelo nunca é a fonte da verdade; a refatoração não pode exigir migração destrutiva nem
perder histórico.

### Consequências

Nenhuma refatoração de código pode alterar o formato persistido sem migração, teste e
documentação.

---

## ADR-005: O modelo como peça substituível

**Status:** Aceito (mantido) · **Data:** 2026-10

### Decisão

O provedor é resolvido por nome (arquivo de provedores → embutidos → mock), e a escolha é
explícita: nome desconhecido é erro, e o mock só entra com autorização. A política de escolha
é injetável (`ExecutionRuntime.provider_factory`), o que permite trocar o provedor sem
tocar no núcleo e injetar um provedor falso nos testes.

### Consequências

Trocar de modelo não exige mudança no orquestrador; o perfil do modelo (limites de contexto e
geração) continua sendo a forma de casar a operação com a capacidade do provedor.

---

**Voltar:** [docs/architecture/README.md](/docs/architecture/README.md) · [docs/README.md](/docs/README.md)
