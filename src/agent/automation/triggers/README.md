# Gatilhos das automações

**Quando** a automação dispara. Um gatilho é um contrato temporal ou de evento: o supervisor
pergunta quais automações estão elegíveis e o resultado vira um disparo.

| Arquivo | Responsabilidade |
|---------|------------------|
| [`base.py`](base.py) | Contrato `Trigger` e o registro de tipos (`register_trigger`, `trigger_factories`, `build_trigger`) |
| [`temporal.py`](temporal.py) | Gatilhos temporais: `once`, `cron` e `interval` (com fuso e horário de verão) |
| [`internal.py`](internal.py) | Gatilho de evento interno: dispara quando o próprio Callidus produz um evento |

## 🔄 Como o gatilho é consultado

1. O supervisor lista as automações ativas.
2. Para cada uma, o `executor.py` pergunta ao gatilho as instâncias elegíveis
   (`next_occurrence` / `occurrences`).
3. O instante elegível vira a chave de idempotência do disparo — o mesmo instante não
   dispara duas vezes, mesmo após uma reinicialização.

O tratamento de fuso, horário de verão e horário inexistente fica em
[`timezones.py`](../timezones.py); o gatilho não decide isso sozinho.

**Voltar:** [automation/README.md](../README.md) · **Voltar:** [src/agent/README.md](../../README.md) · [Raiz](/README.md)