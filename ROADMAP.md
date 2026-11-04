# Roadmap do Callidus

Em que estágio o Callidus está e quanto falta para o próximo.

Detalhes: [docs/progresso/](/docs/progresso/README.md) · Fila: [gaps.md](/docs/progresso/gaps.md) · Formato: [progresso.md](/docs/regras/progresso.md)

> **Revisado em:** 2026-11-04 · **Atualizado em:** 2026-11-04 · **Mudança:** minor (G16; handoff e roteamento por especialidade)

**Estágio:** alpha · **Próximo:** beta (critérios propostos, aguardando o dono)

## 📊 Números principais

| | Valor | Tipo |
|---|-------|------|
| Fluxos centrais que passam no portão do alpha | 6 / 6 (1 com ressalvas) | medido |
| Cenários aceitos com o modelo local (`gpt-oss:20b`) | 15 / 15 | medido (2026-10-20) |
| Testes Python / testes da interface | 1 461 casos passam / 127 passam | medido (2026-11-03, cópia limpa do `HEAD` + esta entrega) |
| Qualidade geral | ~63 % | estimado |
| Horas até o beta | ~34 h | estimado |
| Horas para fechar toda a fila | ~113 h | estimado |

## 📐 Por dimensão

| Dimensão | % | Horas | Checklist |
|----------|---|-------|-----------|
| Funcionalidades | ~60 | 58 | [funcionalidades.md](/docs/progresso/checklists/funcionalidades.md) |
| Interface | ~65 | 10 | [interface.md](/docs/progresso/checklists/interface.md) |
| Desempenho | ~45 | 10 | [desempenho.md](/docs/progresso/checklists/desempenho.md) |
| Segurança | ~60 | 8 | [seguranca.md](/docs/progresso/checklists/seguranca.md) |
| Plataformas | ~50 | 23 | [plataformas.md](/docs/progresso/checklists/plataformas.md) |
| Qualidade | ~80 | 8 | [qualidade.md](/docs/progresso/checklists/qualidade.md) |

## ⏭️ Próximos

1. [G1 Avaliação real ampla e repetível](/docs/progresso/gaps.md#g1-avaliação-real-ampla-e-repetível) — sem ela, toda nota é estimativa.
2. [G2 Decomposição em repositórios grandes](/docs/progresso/gaps.md#g2-decomposição-em-repositórios-grandes)
3. [G16 Fidelidade do artefato e verificação da entrega](/docs/progresso/gaps.md#g16-fidelidade-do-artefato-e-verificação-da-entrega)
4. [G3 Recuperação quando a verificação reprova](/docs/progresso/gaps.md#g3-recuperação-quando-a-verificação-reprova)
5. [G4 Aprovação granular de ferramentas arriscadas na UI](/docs/progresso/gaps.md#g4-aprovação-granular-de-ferramentas-arriscadas-na-ui)

## 📝 Log de progresso

| Data | O que entrou |
|------|--------------|
| 2026-11-04 | G16: evidência de arquivo precisa corresponder ao artefato pedido; piso de qualidade web; handoff visível na Organização; consulta prioriza especialidade; site de culinária refeito e validado no navegador. A verificação universal continua pendente. |
| 2026-11-03 | Organização de engenharia: catálogo de equipes, papéis e propriedade dos módulos; atribuição determinística quando o agente nasce; contrato de trabalho, handoff estruturado, portões G0–G4 derivados das evidências e revisão independente que pode reprovar; indicadores de entrega com denominador; aba Organização; CI remoto no GitHub Actions; 28 testes novos (1461 na suíte, *medido* numa cópia limpa) ([docs/engineering/](/docs/engineering/README.md)) |
| 2026-11-02 | Avaliação real das Etapas 1 e 2 com `gpt-oss:20b` e `qwen3-vl:8b`: seis defeitos achados e corrigidos (resposta final inválida derrubava o run; `git_status` fora de repositório repetido; pytest verde sem evidência; escrita que apagava o arquivo aprovada; etapa de testes e alteração já feita recusadas como saída inválida) — `bug` e `arquivo_grande` passaram a concluir nos dois modelos, sem conclusão falsa ([avaliacao.md](/docs/architecture/avaliacao.md#-etapas-1-e-2--confiabilidade-e-decomposição-02112026)) |
| 2026-11-02 | Etapas 1 e 2 — confiabilidade e decomposição: portão de verificação único (o gate paralelo aprovava por verificador mais fraco), conclusão sem verificador registrada, critério não satisfeito na recuperação, aprovação granular por operação com pausa e retomada, retomada sem repetir operação não repetível, rollback que preserva alteração de terceiros, pai com critério próprio passa pelo portão, irmã desatualizada é reverificada (não reexecutada), plano direto para "leia e explique", resumos estruturados; 8 cenários de integração ([confiabilidade-decomposicao.md](/docs/architecture/confiabilidade-decomposicao.md)) |
| 2026-11-02 | Narração do agente em tempo real: a fala pública do modelo chega à Atividade do agente fragmento a fragmento, sem inferência extra (primeiro trecho a 355 ms com `qwen3-vl:8b`, *medido*); chamadas de ferramenta deixaram de se perder nos streams de OpenAI-compatível, llama.cpp, Anthropic e Gemini ([narracao-tempo-real.md](/docs/architecture/narracao-tempo-real.md)) |
| 2026-10-27 | `qwen3-vl:8b` real na tarefa média: o run deixou de quebrar (antes: 3 de 3 com exceção) e passou a escrever o código certo; plano de 2 048 tokens vazios para ~500 tokens úteis, operação concluída de 15–295 s para 6–27 s (bloco de raciocínio vazio, janela que acompanha a reserva, prova por arquivo, `pytest` sem testes, chamadas em JSON solto); conclusão comprovada ainda pendente ([avaliacao.md](/docs/architecture/avaliacao.md)) |
| 2026-10-22 | Adaptação ao `qwen3:8b`: janela e saída explícitas no Ollama, estimativa de tokens calibrada (real/estimado era 1,30), conversa do ciclo de ferramentas dentro da janela, reparo único do plano com esquema, estado de tarefas irmãs fora das regras do projeto; medição com servidor simulado ([avaliacao.md](/docs/architecture/avaliacao.md#-qwen38b--servidor-ollama-simulado)) |
| 2026-10-21 | Documentos de progresso, comando único de verificação (`python scripts/ci.py`), ritual de sessão e decisões do dono no [AGENTS.md](/AGENTS.md) |
| 2026-10-21 | Automação de sistema/desktop, tarefas agendadas pela conversa, piso de qualidade, feed com narração |
| 2026-10-20 | Estratégia de resolução medida: −34 % de chamadas ao modelo, 15/15 aceitos |
| 2026-10-17 | Fatia vertical: núcleo persistente, orquestrador, ferramentas, UI e E2E |

## 🕑 Histórico de revisão

| Data | Mudança | Resumo |
|------|---------|--------|
| 2026-11-04 | minor | Registra G16 e a conclusão das pendências de handoff e roteamento da missão de engenharia |
| 2026-11-03 | minor | Organização de engenharia; G6 (CI remoto, ruff) parcial |
| 2026-11-02 | minor | Etapas 1 e 2; G3 e G4 parciais; contagem de testes |
| 2026-10-22 | minor | Adaptação ao `qwen3:8b` e contagem de testes refeita |
| 2026-10-21 | major | Criação a partir do kit de agentes de IA |
