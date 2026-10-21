"""
Arquivo: tests/test_recovery_policy.py
Nome: test_recovery_policy.py
Propósito: verificar a continuidade depois de uma falha: investigar, pausar ou parar por impedimento real.
Responsabilidade: camada de testes — política de recuperação e a frase que o feed recebe.
Componentes: alternative_continuance, replan_decision, narrate_failure, root_should_recover.
Dependências: agent.orchestrator.recovery_policy, agent.orchestrator.replan, agent.domain.failures.
Observações: não usa rede nem modelo. Cada cenário nomeia a decisão, não uma execução inteira.
"""

from agent.domain.failures import FailureCategory
from agent.orchestrator.approach import approach_signature
from agent.orchestrator.recovery_policy import (
    alternative_continuance,
    mark_open_investigation,
    may_have_partial_effect,
    narrate_failure,
    pause_next_action,
    root_should_recover,
)
from agent.orchestrator.replan import REPLAN_BUDGET, replan_decision


class _Task:
    """Etapa mínima para a política, sem banco."""

    def __init__(self, meta: dict) -> None:
        self.metadata_json = meta
        self.status = "blocked"


def _stopped(meta: dict) -> _Task:
    return _Task(meta)


def test_c_resposta_invalida_pede_ajuste_e_nao_declara_falha_definitiva():
    text = narrate_failure("change_strategy", "invalid_output", "JSON vazio")
    assert "não cumpriu o contrato" in text
    assert "sucesso" not in text.lower()


def test_d_ferramenta_com_argumento_errado_nao_repete_a_mesma_chamada():
    text = narrate_failure("change_strategy", "tool_input", "old_string não encontrado")
    assert "mesmos argumentos" in text
    choice = alternative_continuance({"exhausted": False, "next_change": "corrigir os argumentos"})
    assert choice == "continue"


def test_h_lista_esgotada_ainda_autoriza_uma_investigacao():
    task = _stopped({"approach": {"exhausted": True, "tried": [{"what": "a mesma operação"}]}})
    decision = replan_decision({}, task, completed=0)
    assert decision.replan is True
    assert "investigar" in decision.reason


def test_i_raiz_sem_pai_pode_recuperar_uma_vez():
    assert root_should_recover(has_parent=False, already_recovered=False, replan=True) is True
    assert root_should_recover(has_parent=True, already_recovered=False, replan=True) is False
    assert root_should_recover(has_parent=False, already_recovered=True, replan=True) is False


def test_j_timeout_pode_ter_efeito_parcial():
    assert may_have_partial_effect("timeout") is True
    assert may_have_partial_effect("tool_input") is False
    text = narrate_failure("recoverable", "timeout", "connection timed out")
    assert "não vou repetir" in text.lower()


def test_k_causa_vazia_pede_investigacao():
    text = narrate_failure("change_strategy", "", "boom")
    assert "não está classificada" in text
    assert "investigar" in text


def test_l_configuracao_nao_e_replanejada():
    task = _stopped(
        {
            "last_failure": {
                "category": FailureCategory.CONFIGURATION.value,
                "cause": "provider_credentials",
                "detail": "HTTP 401",
            },
            "approach": {"exhausted": False},
        }
    )
    decision = replan_decision({}, task, completed=1)
    assert decision.replan is False
    assert "ação externa" in decision.reason
    text = narrate_failure("configuration", "provider_credentials", "HTTP 401")
    assert "Não vou contornar" in text


def test_m_indisponibilidade_nao_e_bloqueio_de_configuracao():
    text = narrate_failure("external_unavailable", "provider_unavailable", "connection refused")
    assert "transitória" in text
    assert "Não vou contornar" not in text


def test_n_orcamento_pausa_sem_declarar_impossibilidade():
    text = pause_next_action(total=6, run_id="abc", probable_cause="mesmo erro")
    assert "resume" in text
    assert "não está provada como insolúvel" in text


def test_o_investigacao_ja_usada_nao_replaneja_de_novo():
    task = _stopped({"approach": {"exhausted": True, "open_investigation": True}})
    decision = replan_decision({}, task, completed=1)
    assert decision.replan is False
    assert "investigação aberta" in decision.reason


def test_o_orcamento_de_replanejamento_continua_valendo():
    task = _stopped({"approach": {"exhausted": True}})
    decision = replan_decision({"replan_count": REPLAN_BUDGET}, task, completed=1)
    assert decision.replan is False
    assert "limite" in decision.reason


def test_r_investigacao_muda_a_assinatura_e_preserva_o_historico():
    task = _stopped(
        {
            "approach": {
                "cause": "tool_error",
                "current_change": "a mesma operação",
                "exhausted": True,
                "tried": [{"what": "a mesma operação", "result": "falhou"}],
            }
        }
    )
    before = approach_signature(task)
    updated = mark_open_investigation(task)
    assert updated["tried"][0]["what"] == "a mesma operação"
    assert updated["open_investigation"] is True
    assert approach_signature(task) != before


def test_replanejar_sem_progresso_continua_recusado_quando_ainda_ha_alternativa():
    task = _stopped(
        {
            "blocked_reason": "pytest falhou em 0.52s",
            "approach": {"exhausted": False, "next_change": "dividir a etapa"},
        }
    )
    history = {"replan_count": 1, "replan_history": [{"completed": 0, "reason": "pytest falhou em 0.31s"}]}
    assert replan_decision(history, task, completed=0).replan is False
    assert replan_decision(history, task, completed=1).replan is True
