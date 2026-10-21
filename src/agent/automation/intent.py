"""
Arquivo: src/agent/automation/intent.py
Nome: intent.py
Propósito: reconhecer quando o pedido da conversa é sobre tarefas agendadas.
Responsabilidade: camada de domínio — detecção de intenção; não executa nem grava.
Componentes: is_automation_request, looks_like_schedule, normalize_text.
Dependências: agent.automation.natural.
Observações: a detecção é uma heurística de desvio de rota, não um contrato; a decisão final é do modelo com as ferramentas.

O Callidus conversa sobre duas coisas diferentes: "o que fazer agora" e "o que
fazer mais tarde". Esta módulo diz qual das duas é, para que o pedido de
agendamento não caia no caminho de edição de arquivos — e para que um pedido
normal de código não seja desviado para o caminho de automação.

A heurística é deliberadamente conservadora: palavra forte (automação,
agendamento) basta; palavra fraca (rotina, agenda, monitoramento) só vale
com um verbo de ação; e uma expressão de horário ("todos os dias às 9h") só
vale com um verbo que pede agendamento.
"""
from __future__ import annotations

import unicodedata

# Palavras que, sozinhas, indicam automação.
_STRONG_NOUNS = (
    "automacao",
    "automacoes",
    "automatizacao",
    "automatizacoes",
    "agendamento",
    "agendamentos",
    "agendada",
    "agendadas",
    "agendado",
    "agendados",
    "tarefa agendada",
    "tarefas agendadas",
    "trabalho agendado",
    "trabalhos agendados",
    "rotina agendada",
    "scheduled task",
)

# Palavras que só indicam automação acompanhadas de um verbo de ação.
_WEAK_NOUNS = (
    "rotina",
    "rotinas",
    "agenda",
    "lembrete",
    "lembretes",
    "monitoramento",
    "monitoring",
)

# Verbos de agendamento: pedem que algo passe a rodar em horário definido.
_SCHEDULE_VERBS = (
    "agende",
    "agendar",
    "agendou",
    "programe",
    "programar",
    "programado",
    "marque",
    "marcar",
    "crie",
    "criar",
    "cria",
    "criado",
    "rode",
    "rodar",
    "executa",
    "executar",
    "faca",
    "fazer",
    "verifique",
    "verificar",
    "analise",
    "analisar",
    "prepare",
    "preparar",
    "gere",
    "gerar",
    "monitore",
    "monitorar",
    "acompanhe",
    "confira",
    "conferir",
    "notifique",
    "notificar",
    "avise",
    "avisar",
    "me avise",
    "avise-me",
)

# Verbos de gerenciamento: consultam ou mudam o estado de algo já agendado.
_MANAGE_VERBS = (
    "pause",
    "pausar",
    "pausa",
    "pausado",
    "pausada",
    "suspende",
    "suspender",
    "suspensa",
    "retome",
    "retomar",
    "retoma",
    "reative",
    "reativar",
    "desative",
    "desativar",
    "liste",
    "listar",
    "mostre",
    "mostrar",
    "exclua",
    "excluir",
    "remova",
    "remover",
    "apague",
    "apagar",
    "cancele",
    "cancelar",
    "execute",
    "executar",
    "rode",
    "rodar",
    "teste",
    "testar",
    "diagnostico",
    "diagnosticar",
    "historico",
    "altere",
    "alterar",
    "mude",
    "mudar",
    "mude para",
    "mudar para",
    "troque",
    "trocar",
    "edite",
    "editar",
    "alterar",
    "confirme",
    "confirmar",
    "ative",
    "ativar",
)

_SCHEDULE_HINTS = (
    "todo dia",
    "todos os dias",
    "toda semana",
    "todo mes",
    "toda segunda",
    "toda terca",
    "toda quarta",
    "toda quinta",
    "toda sexta",
    "todo sabado",
    "todo domingo",
    "a cada",
    "daqui a",
    "todo dia",
    "diaria",
    "diariamente",
    "diario",
    "semanal",
    "semanalmente",
    "every day",
    "daily",
    "weekly",
    # Horários imprecisos: o usuário **está** pedindo um horário, mesmo que o
    # interpretador não possa escolhê-lo. O caminho da automação pergunta.
    "de manha",
    "a tarde",
    "a noite",
    "mais tarde",
)


def normalize_text(text: str) -> str:
    """Texto em minúsculas e sem acentos, para comparação tolerante.

    Args:
        text: texto de entrada.

    Returns:
        O texto normalizado.
    """
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    return " ".join("".join(ch for ch in decomposed if not unicodedata.combining(ch)).split())


def looks_like_schedule(text: str) -> bool:
    """Diz se o texto carrega uma expressão de horário ou recorrência.

    Args:
        text: pedido do usuário.

    Returns:
        `True` quando há expressão de data, hora ou recorrência.

    Observações:
        Só conta a expressão que virou **gatilho**: "amanhã" sozinho é uma data
        citada, não um pedido de agendamento — o texto vira pergunta sobre o
        horário, e não um desvio para o caminho das automações.
    """
    from agent.automation.natural import parse_schedule

    raw = normalize_text(text)
    if any(hint in raw for hint in _SCHEDULE_HINTS):
        return True
    return parse_schedule(text).resolved


# Confirmações curtas: o usuário concorda com a prévia. Sozinhas não dizem do que
# estão falando — o contexto da conversa diz.
_CONFIRMATIONS = (
    "sim",
    "ok",
    "certo",
    "feito",
    "pode",
    "pode ativar",
    "pode prosseguir",
    "autorizo",
    "autorize",
    "ative",
    "ativar",
    "confirme",
    "confirmar",
    "prosseguir",
)


def is_confirmation(text: str) -> bool:
    """Diz se o texto é uma confirmação curta de algo já apresentado.

    Args:
        text: pedido do usuário.

    Returns:
        `True` quando o texto é uma concordância breve.

    Observações:
        O texto sozinho não diz do que se trata: quem dá o sentido é a conversa.
    """
    raw = normalize_text(text)
    if not raw or len(raw.split()) > 6:
        return False
    return any(word in raw for word in _CONFIRMATIONS)


def is_automation_request(
    text: str, *, previous: list[str] | None = None
) -> bool:
    """Diz se o pedido é sobre tarefas agendadas.

    Args:
        text: pedido do usuário.
        previous: pedidos anteriores da mesma conversa, do mais recente ao mais antigo.

    Returns:
        `True` quando o pedido deve ir para o caminho de automações.

    Observações:
        Três caminhos de sinal, do mais forte ao mais fraco:

        1. palavra forte ("automação", "agendamento") — basta;
        2. palavra fraca ("rotina", "agenda") com verbo de ação;
        3. expressão de horário com verbo de agendamento.

        E um quarto, que vem do contexto: uma confirmação curta ("sim, pode ativar")
        depois de um pedido de automação é a confirmação daquela automação.
    """
    raw = normalize_text(text)
    if not raw:
        return False
    if any(noun in raw for noun in _STRONG_NOUNS):
        return True
    has_verb = any(verb in raw for verb in _SCHEDULE_VERBS + _MANAGE_VERBS)
    if has_verb and any(noun in raw for noun in _WEAK_NOUNS):
        return True
    if has_verb and looks_like_schedule(text):
        return True
    if previous and is_confirmation(text):
        for item in previous:
            if is_automation_request(item):
                return True
    return False


__all__ = [
    "is_automation_request",
    "is_confirmation",
    "looks_like_schedule",
    "normalize_text",
]
