"""
Arquivo: tests/test_automation_natural.py
Nome: test_automation_natural.py
Propósito: Verificar a interpretação de horários em linguagem natural e a detecção de intenção de automação.
Responsabilidade: camada de testes — datas relativas, recorrências, fusos, ambiguidade e desvio de rota.
Componentes: parse_schedule, describe_cron, is_automation_request.
Dependências: agent.automation.natural, agent.automation.intent.
Observações: o instante de referência é fixo — o teste não depende do relógio real.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agent.automation.intent import is_automation_request, is_confirmation
from agent.automation.natural import describe_cron, parse_schedule

# Instante fixo: quarta-feira, 21/10/2026, 12:00 em São Paulo.
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))


def _parse(text: str, **kwargs):
    """Interpreta um texto com o instante de referência fixo."""
    return parse_schedule(text, now=NOW, **kwargs)


def test_recorrencia_diaria_vira_cron():
    """«Todos os dias às 9h» vira a recorrência diária no fuso do usuário."""
    intent = _parse("Todos os dias às 9h, verifique os testes")
    assert intent.kind == "cron"
    assert intent.resolved
    assert intent.trigger is not None
    assert intent.trigger.cron == "0 9 * * *"
    assert intent.trigger.timezone == "America/Sao_Paulo"


def test_recorrencia_semanal_vira_cron_com_dia_da_semana():
    """«Todas as segundas-feiras às 8h30» vira a segunda da semana."""
    intent = _parse("Todas as segundas-feiras, às 8h30, prepare um resumo")
    assert intent.resolved
    assert intent.trigger is not None
    assert intent.trigger.cron == "30 8 * * 1"


def test_execucao_unica_usa_a_data_real():
    """«Amanhã às 14h» vira uma execução única, calculada com a data do sistema."""
    intent = _parse("Amanhã, às 14h, execute esta tarefa")
    assert intent.kind == "once"
    assert intent.resolved
    assert intent.trigger is not None
    assert intent.trigger.run_at is not None
    assert intent.trigger.run_at.astimezone(ZoneInfo("America/Sao_Paulo")).strftime(
        "%d/%m/%Y %H:%M"
    ) == "22/10/2026 14:00"


def test_intervalo_por_horas_e_por_extenso():
    """«A cada quatro horas» vira um intervalo, e não um horário."""
    for text in ("A cada quatro horas", "A cada 4 horas"):
        intent = _parse(text)
        assert intent.kind == "interval"
        assert intent.trigger is not None
        assert intent.trigger.interval_seconds == 4 * 3600


def test_ultimo_dia_do_mes_vira_cron():
    """«No último dia de cada mês às 23h» vira a recorrência do fim do mês."""
    intent = _parse("no último dia de cada mês às 23h")
    assert intent.resolved
    assert intent.trigger is not None
    assert intent.trigger.cron == "0 23 L * *"


def test_horario_impreciso_pergunta_em_vez_de_escolher():
    """«De manhã» não vira horário: o módulo pergunta."""
    intent = _parse("de manhã")
    assert not intent.resolved
    assert intent.needs_clarification
    assert intent.question


def test_recorrencia_sem_horario_pergunta():
    """«Todo dia» sem hora pergunta o horário, em vez de inventar um."""
    intent = _parse("todo dia")
    assert not intent.resolved
    assert intent.question


def test_horario_no_passado_pergunta():
    """Um horário que já passou pede confirmação, em vez de reagendar sozinho."""
    intent = _parse("hoje às 9h")
    assert not intent.resolved
    assert "já passou" in (intent.question or "")


def test_expressao_relativa_com_horario_exato():
    """«Daqui a duas horas» vira um instante exato."""
    intent = _parse("daqui a duas horas")
    assert intent.kind == "once"
    assert intent.trigger is not None
    assert intent.trigger.run_at is not None
    assert intent.trigger.run_at.astimezone(ZoneInfo("America/Sao_Paulo")).strftime(
        "%H:%M"
    ) == "14:00"


def test_fuso_configurado_e_respeitado():
    """O fuso pedido pelo usuário é o usado no gatilho."""
    intent = _parse("todos os dias às 9h", timezone="UTC")
    assert intent.trigger is not None
    assert intent.trigger.timezone == "UTC"
    assert intent.trigger.cron == "0 9 * * *"


def test_describe_cron_em_portugues():
    """A descrição de um cron conhecido é lida em português."""
    assert describe_cron("0 9 * * *") == "todos os dias às 09:00"
    assert describe_cron("30 8 * * 1") == "toda segunda-feira às 08:30"
    assert describe_cron("0 23 L * *") == "no último dia de cada mês às 23:00"


@pytest.mark.parametrize(
    "text",
    [
        "Todos os dias às 9h, verifique os testes e me avise",
        "Todas as segundas-feiras, às 8h30, prepare um resumo",
        "Amanhã, às 14h, execute esta tarefa",
        "A cada quatro horas, verifique o serviço",
        "Quais tarefas estão agendadas para hoje?",
        "Mude a verificação diária para as 10h.",
        "Pause o monitoramento até eu mandar retomar.",
        "Execute agora a automação de verificação dos testes.",
        "Exclua a automação de relatório semanal.",
        "Por que minha automação não executou hoje?",
    ],
)
def test_pedido_de_automacao_e_reconhecido(text):
    """O pedido sobre tarefa agendada é reconhecido como automação."""
    assert is_automation_request(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Verifique os testes do projeto e me informe as falhas.",
        "Rode os testes agora.",
        "Verifique os testes amanhã",
        "Amanhã eu preciso revisar o código",
        "Crie um arquivo main.py com uma função de soma.",
        "Explique o que este repositório faz.",
        "Execute o script de deploy",
        "Liste os arquivos do projeto.",
    ],
)
def test_pedido_comum_nao_vira_automacao(text):
    """Um pedido que não é de agendamento não é desviado para o caminho das automações."""
    assert is_automation_request(text) is False


def test_confirmacao_curta_vira_automacao_quando_o_contexto_e_de_automacao():
    """«Sim, pode ativar» depois de um pedido de automação é a confirmação daquela automação."""
    previous = ["Todos os dias às 9h, verifique os testes deste projeto."]
    assert is_automation_request("Sim, pode ativar.", previous=previous) is True
    assert is_automation_request("pode ativar essa automação", previous=previous) is True


def test_confirmacao_curta_sem_contexto_de_automacao_nao_vira_automacao():
    """Sem contexto de automação, uma confirmação curta não desvia a rota."""
    previous = ["Explique o que este repositório faz."]
    assert is_automation_request("Sim, pode ativar.", previous=previous) is False
    assert is_automation_request("Sim, pode ativar.") is False


def test_confirmacao_exige_frase_curta():
    """Uma frase longa não é tratada como confirmação."""
    assert is_confirmation("Sim") is True
    assert is_confirmation("sim, pode ativar") is True
    assert (
        is_confirmation(
            "Sim, pode ativar, mas só depois de revisar o relatório inteiro do projeto"
        )
        is False
    )
