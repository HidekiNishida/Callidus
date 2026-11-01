"""
Arquivo: tests/test_learning_profiles.py
Nome: test_learning_profiles.py
Propósito: testar os perfis operacionais e seus limites aplicados.
Responsabilidade: camada de testes — seleção de perfil por tipo de trabalho,
aplicação dos limites globais de configuração, registro e sobreposição de perfis.
Componentes: OperationalProfile, ProfileLimit, ProfileCatalog, profile_for,
register_profile, override_limit, clear_override.
Dependências: agent.learning.profiles, agent.config, pytest.
Observações: usa Settings do ambiente; nenhum banco real é tocado.
"""

from agent.config import Settings
from agent.learning.profiles import (
    DecompositionGranularity,
    OperationalProfile,
    ProfileCatalog,
    ProfileLimit,
    VerificationIntensity,
    create_profile_catalog,
)


def _catalog() -> ProfileCatalog:
    return create_profile_catalog(Settings())


def test_profile_for_returns_limites_aplicados():
    """O perfil de implementação traz limites aplicados (capped pelos globais)."""
    cat = _catalog()
    prof = cat.profile_for("implementacao")
    assert prof.work_type == "implementacao"
    assert prof.requires_model is True
    assert prof.deterministic_first is False
    lim = prof.limit
    assert lim.context_budget == 8192
    assert lim.output_reserve == 1024
    assert lim.decomposition_granularity == DecompositionGranularity.HIERARCHICAL
    assert lim.max_attempts == 3
    assert lim.verification_intensity == VerificationIntensity.HIGH


def test_consulta_eh_deterministico_sem_modelo():
    """A consulta resolve sem modelo e de forma determinística primeiro."""
    cat = _catalog()
    prof = cat.profile_for("consulta")
    assert prof.requires_model is False
    assert prof.deterministic_first is True
    lim = prof.limit
    assert lim.decomposition_granularity == DecompositionGranularity.SIMPLE
    assert lim.max_attempts == 1


def test_work_types_listagem():
    """Lista todos os tipos de trabalho esperados."""
    cat = _catalog()
    tipos = cat.work_types()
    esperado = [
        "automacao",
        "consulta",
        "correcao",
        "documentacao",
        "implementacao",
        "investigacao",
        "pesquisa",
        "planejamento",
        "refatoracao",
        "testes",
        "verificacao",
    ]
    assert tipos == esperado


def test_limite_global_capa_orcamento_contexto():
    """Um perfil com orçamento acima do global é capado pelo default_context_limit."""
    cat = _catalog()
    cat.register_profile(
        OperationalProfile(
            work_type="implementacao",
            description="sobrescrito",
            limit=ProfileLimit(
                context_budget=200_000,
                output_reserve=50_000,
                max_attempts=999,
                max_model_calls=999_999,
                timeout_sec=999_999,
            ),
        )
    )
    lim = cat.profile_for("implementacao").limit
    settings = Settings()
    assert lim.context_budget <= settings.default_context_limit
    assert lim.output_reserve <= settings.default_output_reserve
    assert lim.max_attempts <= settings.max_attempts_per_task
    assert lim.max_model_calls <= settings.max_model_calls_per_run
    assert lim.timeout_sec <= settings.agent_operation_timeout_sec


def test_override_e_clear_override():
    """A sobreposição altera o limite e o clear_override restaura o padrão."""
    cat = _catalog()
    antes = cat.profile_for("correcao").limit.max_attempts
    cat.override_limit(
        "correcao",
        ProfileLimit(
                context_budget=1000,
            output_reserve=100,
            max_attempts=7,
            max_tool_calls=3,
            verification_intensity=VerificationIntensity.LOW,
        ),
    )
    depois = cat.profile_for("correcao").limit
    assert depois.max_attempts == 7
    assert depois.max_tool_calls == 3
    assert depois.verification_intensity == VerificationIntensity.LOW
    cat.clear_override("correcao")
    restaurado = cat.profile_for("correcao").limit
    assert restaurado.max_attempts == antes


def test_perfil_desconhecido_cai_no_planejamento():
    """Tipo de trabalho desconhecido usa o perfil de planejamento como fallback."""
    cat = _catalog()
    prof = cat.profile_for("tipo_inexistente")
    assert prof.work_type == "planejamento"
