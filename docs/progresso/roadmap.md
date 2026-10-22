# Roadmap detalhado

O portão do próximo estágio do Callidus e os marcos até ele.

Voltar: [docs/progresso/](/docs/progresso/README.md) · Resumo: [ROADMAP.md](/ROADMAP.md) · Fila: [gaps.md](/docs/progresso/gaps.md)

> **Revisado em:** 2026-10-21 · **Atualizado em:** 2026-10-21 · **Mudança:** major (criação)

## 🚦 Portão do alpha (atual)

Todo fluxo central precisa funcionar ponta a ponta, com evidência.

| Fluxo central | Funciona ponta a ponta? | Evidência | Horas |
|---------------|-------------------------|-----------|-------|
| Pedido no chat → plano → execução → verificação → resposta final | Sim | 15/15 cenários aceitos com `gpt-oss:20b` (*medido*, 2026-10-20, [avaliação](/docs/architecture/avaliacao.md)) | 0 |
| Falha → estagnação → replanejamento → pausa/retomada | Sim | falha injetada determinística; `tests/test_orchestrator_recovery.py` | 0 |
| Pedido somente leitura respeitado | Sim | `verificacao_reprova` 3/3 (*medido*) | 0 |
| Feed ao vivo e histórico ao reabrir a conversa | Sim, com ressalvas ([G5](/docs/progresso/gaps.md#g5-defeitos-conhecidos-do-feed)) | auditoria de 2026-10-21; `tests/web/narrative-replay.test.mjs` | 5 |
| Configurar provedor e modelo pela interface | Sim | `tests/test_providers_api.py`, `tests/test_provider_config_api.py` | 0 |
| Automações persistentes pedidas pela conversa | Sim (só testes, sem uso real registrado) | `tests/test_automation_end_to_end.py`, `tests/test_automation_chat_flow.py` | 0 |

**Leitura honesta:** o Callidus está em **alpha**. Os fluxos passam, mas a amostra com o modelo real é pequena ([G1](/docs/progresso/gaps.md#g1-avaliação-real-ampla-e-repetível)).

## 🚦 Portão do beta (proposta — decisão do dono)

Critérios propostos, ainda **não aprovados pelo dono**:

| Critério | Gap | Horas |
|----------|-----|-------|
| Avaliação com ≥ 15 cenários, incluindo uma sessão longa, em ≥ 3 rodadas | [G1](/docs/progresso/gaps.md#g1-avaliação-real-ampla-e-repetível) | 10 |
| Decomposição útil num repositório grande real | [G2](/docs/progresso/gaps.md#g2-decomposição-em-repositórios-grandes) | 16 |
| Recuperação de verificação reprovada sem repetir o mesmo verificador | [G3](/docs/progresso/gaps.md#g3-recuperação-quando-a-verificação-reprova) | 8 |
| Aprovação de ferramenta arriscada item a item na UI | [G4](/docs/progresso/gaps.md#g4-aprovação-granular-de-ferramentas-arriscadas-na-ui) | 8 |
| Versão única e licença definida | [G13](/docs/progresso/gaps.md#g13-versão-e-licença) | 1 |

## 🎯 Foco atual

[G1](/docs/progresso/gaps.md#g1-avaliação-real-ampla-e-repetível): sem uma avaliação maior, qualquer nota de qualidade é estimativa.

## 🗺️ Marcos

| # | Marco | Status | Restante (h) |
|---|-------|--------|--------------|
| M0 | Fatia vertical: pedido → resposta verificada com modelo local | ✅ feito (2026-10-17) | 0 |
| M1 | Verificação independente, requisitos rastreáveis e aceite global | ✅ feito | 0 |
| M2 | Estagnação, memória de abordagem e falha injetada medida | ✅ feito (2026-10-20) | 0 |
| M3 | Hierarquia de agentes, automações e automação de sistema | ✅ feito (2026-10-21) | 0 |
| M4 | Avaliação ampla + portão de beta aprovado pelo dono | ☐ | 10 |
| M5 | Beta: G2, G3, G4, G13 fechados | ☐ | 33 |

Horas *estimadas*.

## 🕑 Histórico de revisão

| Data | Mudança | Resumo |
|------|---------|--------|
| 2026-10-21 | major | Criação: portão do alpha com evidência, proposta de beta e marcos M0–M5 |
