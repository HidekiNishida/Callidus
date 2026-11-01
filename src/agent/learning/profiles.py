"""
Arquivo: src/agent/learning/profiles.py
Nome: profiles.py
Propósito: perfis operacionais com limites configuráveis por tipo de trabalho.
Responsabilidade: camada de aplicação — define perfis nomeados (consulta,
investigação, planejamento, implementação, correção, refatoração, testes,
documentação, verificação, pesquisa, automação) com orçamento de contexto,
reserva de saída, granularidade de decomposição, profundidade recursiva,
tentativas, inspeções, skills, intensidade de verificação e limites de execução.
Componentes: OperationalProfile, ProfileLimit, ProfileCatalog, profile_for,
register_profile.
Dependências: agent.config (Settings), dataclasses, typing.
Observações: os valores são defaults seguros e nunca ultrapassam os limites
globais de configuração (max_context_limit, max_attempts_per_task, etc.). Um
perfil é uma receita de execução, não um modelo; não altera pesos nem código.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from agent.config import Settings


class DecompositionGranularity(str):
    """Granularidade de decomposição de uma tarefa."""

    SIMPLE = "simple"      # sem decomposição: resposta direta ou ferramenta determinística
    HIERARCHICAL = "hierarchical"  # plano com tarefas filhas, um nível
    RECURSIVE = "recursive"        # decomposição recursiva em sub-tarefas


class VerificationIntensity(str):
    """Intensidade de verificação de um perfil."""

    LOW = "low"     # verificação apenas do entregável final
    MEDIUM = "medium"  # verificação do entregável + integrações diretas
    HIGH = "high"    # verificação independente, globais, contratos e evidências


@dataclass(frozen=True)
class ProfileLimit:
    """Limite operacional de um perfil para um tipo de trabalho.

    Atributos:
        context_budget: orçamento de tokens de entrada para o modelo.
        output_reserve: reserva de tokens de saída que a implementação não pode gastar.
        decomposition_granularity: granularidade de decomposição (simple/hierarchical/recursive).
        max_recursion_depth: profundidade máxima de delegação recursiva.
        max_attempts: quantidade máxima de tentativas por problema.
        max_inspections: número máximo de leituras de inspeção.
        max_tool_iterations: rodadas do ciclo de ferramentas por operação.
        max_tool_calls: total de chamadas de ferramenta no ciclo.
        verification_intensity: intensidade de verificação.
        skills_selected: skills selecionadas (None = todas habilitadas).
        max_model_calls: chamadas ao modelo permitidas na execução.
        timeout_sec: tempo limite da operação em segundos.
    """

    context_budget: int
    output_reserve: int
    decomposition_granularity: str = DecompositionGranularity.HIERARCHICAL
    max_recursion_depth: int = 2
    max_attempts: int = 3
    max_inspections: int = 2
    max_tool_iterations: int = 4
    max_tool_calls: int = 8
    verification_intensity: str = VerificationIntensity.MEDIUM
    skills_selected: list[str] | None = None
    max_model_calls: int = 400
    timeout_sec: float = 300.0


@dataclass(frozen=True)
class OperationalProfile:
    """Perfil operacional completo para um tipo de trabalho.

    Atributos:
        work_type: tipo de trabalho (consulta, investigação, planejamento,
            implementação, correção, refatoração, testes, documentação,
            verificação, pesquisa, automação).
        description: descrição legível do perfil.
        limit: limites operacionais.
        requires_model: se o perfil exige inferência do modelo (False = determinístico).
        deterministic_first: se tenta resolver com ferramenta determinística antes do modelo.
    """

    work_type: str
    description: str
    limit: ProfileLimit
    requires_model: bool = True
    deterministic_first: bool = False


# Perfis padrões. Os limites respeitam os globais de Settings; quando um valor
# de perfil excede o global, o global vence na aplicação (ver ProfileCatalog.apply).
_DEFAULT_PROFILES: dict[str, OperationalProfile] = {
    "consulta": OperationalProfile(
        work_type="consulta",
        description="Resposta direta a uma pergunta, sem planejamento hierárquico.",
        limit=ProfileLimit(
            context_budget=2048,
            output_reserve=512,
            decomposition_granularity=DecompositionGranularity.SIMPLE,
            max_recursion_depth=0,
            max_attempts=1,
            max_inspections=1,
            max_tool_iterations=1,
            max_tool_calls=2,
            verification_intensity=VerificationIntensity.LOW,
            max_model_calls=50,
            timeout_sec=120.0,
        ),
        deterministic_first=True,
        requires_model=False,
    ),
    "investigacao": OperationalProfile(
        work_type="investigacao",
        description="Investiga um bug ou comportamento antes de implementar.",
        limit=ProfileLimit(
            context_budget=4096,
            output_reserve=1024,
            decomposition_granularity=DecompositionGranularity.SIMPLE,
            max_recursion_depth=1,
            max_attempts=2,
            max_inspections=2,
            max_tool_iterations=2,
            max_tool_calls=6,
            verification_intensity=VerificationIntensity.MEDIUM,
            max_model_calls=120,
            timeout_sec=300.0,
        ),
        deterministic_first=True,
    ),
    "planejamento": OperationalProfile(
        work_type="planejamento",
        description="Produz o plano de decomposição de uma tarefa maior.",
        limit=ProfileLimit(
            context_budget=6000,
            output_reserve=1536,
            decomposition_granularity=DecompositionGranularity.HIERARCHICAL,
            max_recursion_depth=2,
            max_attempts=2,
            max_inspections=2,
            max_tool_iterations=2,
            max_tool_calls=8,
            verification_intensity=VerificationIntensity.MEDIUM,
            max_model_calls=150,
            timeout_sec=300.0,
        ),
    ),
    "implementacao": OperationalProfile(
        work_type="implementacao",
        description="Implementa uma funcionalidade em vários arquivos.",
        limit=ProfileLimit(
            context_budget=8192,
            output_reserve=3072,
            decomposition_granularity=DecompositionGranularity.HIERARCHICAL,
            max_recursion_depth=3,
            max_attempts=3,
            max_inspections=3,
            max_tool_iterations=4,
            max_tool_calls=12,
            verification_intensity=VerificationIntensity.HIGH,
            max_model_calls=300,
            timeout_sec=600.0,
        ),
    ),
    "correcao": OperationalProfile(
        work_type="correcao",
        description="Corrige um bug com diagnóstico de causa.",
        limit=ProfileLimit(
            context_budget=6000,
            output_reserve=2048,
            decomposition_granularity=DecompositionGranularity.HIERARCHICAL,
            max_recursion_depth=2,
            max_attempts=3,
            max_inspections=3,
            max_tool_iterations=3,
            max_tool_calls=10,
            verification_intensity=VerificationIntensity.HIGH,
            max_model_calls=200,
            timeout_sec=600.0,
        ),
        deterministic_first=True,
    ),
    "refatoracao": OperationalProfile(
        work_type="refatoracao",
        description="Refatora um módulo mantendo compatibilidade.",
        limit=ProfileLimit(
            context_budget=8192,
            output_reserve=2560,
            decomposition_granularity=DecompositionGranularity.HIERARCHICAL,
            max_recursion_depth=2,
            max_attempts=2,
            max_inspections=3,
            max_tool_iterations=4,
            max_tool_calls=12,
            verification_intensity=VerificationIntensity.HIGH,
            max_model_calls=250,
            timeout_sec=600.0,
        ),
    ),
    "testes": OperationalProfile(
        work_type="testes",
        description="Acrescenta validação e testes a um módulo.",
        limit=ProfileLimit(
            context_budget=4096,
            output_reserve=1536,
            decomposition_granularity=DecompositionGranularity.SIMPLE,
            max_recursion_depth=1,
            max_attempts=2,
            max_inspections=2,
            max_tool_iterations=2,
            max_tool_calls=8,
            verification_intensity=VerificationIntensity.HIGH,
            max_model_calls=150,
            timeout_sec=300.0,
        ),
    ),
    "documentacao": OperationalProfile(
        work_type="documentacao",
        description="Escreve ou atualiza documentação.",
        limit=ProfileLimit(
            context_budget=4096,
            output_reserve=2048,
            decomposition_granularity=DecompositionGranularity.SIMPLE,
            max_recursion_depth=1,
            max_attempts=1,
            max_inspections=2,
            max_tool_iterations=2,
            max_tool_calls=6,
            verification_intensity=VerificationIntensity.LOW,
            max_model_calls=100,
            timeout_sec=300.0,
        ),
        deterministic_first=False,
    ),
    "verificacao": OperationalProfile(
        work_type="verificacao",
        description="Executa verificação independente de um entregável.",
        limit=ProfileLimit(
            context_budget=4096,
            output_reserve=1024,
            decomposition_granularity=DecompositionGranularity.SIMPLE,
            max_recursion_depth=1,
            max_attempts=2,
            max_inspections=2,
            max_tool_iterations=1,
            max_tool_calls=4,
            verification_intensity=VerificationIntensity.HIGH,
            max_model_calls=80,
            timeout_sec=300.0,
        ),
        deterministic_first=True,
    ),
    "pesquisa": OperationalProfile(
        work_type="pesquisa",
        description="Investiga alternativas antes de decidir a implementação.",
        limit=ProfileLimit(
            context_budget=8192,
            output_reserve=3072,
            decomposition_granularity=DecompositionGranularity.RECURSIVE,
            max_recursion_depth=3,
            max_attempts=3,
            max_inspections=4,
            max_tool_iterations=4,
            max_tool_calls=16,
            verification_intensity=VerificationIntensity.MEDIUM,
            max_model_calls=300,
            timeout_sec=900.0,
        ),
    ),
    "automacao": OperationalProfile(
        work_type="automacao",
        description="Executa automação agendada ou disparada por evento.",
        limit=ProfileLimit(
            context_budget=4096,
            output_reserve=1024,
            decomposition_granularity=DecompositionGranularity.SIMPLE,
            max_recursion_depth=1,
            max_attempts=1,
            max_inspections=1,
            max_tool_iterations=1,
            max_tool_calls=4,
            verification_intensity=VerificationIntensity.MEDIUM,
            max_model_calls=100,
            timeout_sec=300.0,
        ),
        deterministic_first=True,
    ),
}


class ProfileCatalog:
    """Catálogo de perfis operacionais com sobreposições por run."""

    def __init__(self, settings: Settings) -> None:
        """Cria o catálogo com os perfis padrões.

        Args:
            settings: configurações do processo (fornece os limites globais).
        """
        self._settings = settings
        self._profiles: dict[str, OperationalProfile] = dict(_DEFAULT_PROFILES)
        self._overrides: dict[str, ProfileLimit] = {}

    def profile_for(self, work_type: str) -> OperationalProfile:
        """Devolve o perfil para um tipo de trabalho, aplicando limites globais.

        Args:
            work_type: tipo de trabalho.

        Returns:
            O perfil operacional, com limites ajustados aos globais de configuração.
        """
        profile = self._profiles.get(work_type)
        if profile is None:
            profile = self._profiles["planejamento"]
        override = self._overrides.get(work_type)
        limit = profile.limit if override is None else override
        return replace(profile, limit=self._apply_global_limits(limit))

    def _apply_global_limits(self, limit: ProfileLimit) -> ProfileLimit:
        """Aplica os limites globais de configuração como teto do perfil.

        Args:
            limit: limite do perfil.

        Returns:
            O limite com valores capados aos globais de Settings.
        """
        s = self._settings
        return ProfileLimit(
            context_budget=min(limit.context_budget, s.default_context_limit),
            output_reserve=min(limit.output_reserve, s.default_output_reserve),
            decomposition_granularity=limit.decomposition_granularity,
            max_recursion_depth=min(limit.max_recursion_depth, s.max_tree_depth),
            max_attempts=min(limit.max_attempts, s.max_attempts_per_task),
            max_inspections=min(limit.max_inspections, s.max_agent_depth),
            max_tool_iterations=min(limit.max_tool_iterations, s.max_tool_iterations),
            max_tool_calls=min(limit.max_tool_calls, s.max_tool_calls),
            verification_intensity=limit.verification_intensity,
            skills_selected=limit.skills_selected,
            max_model_calls=min(limit.max_model_calls, s.max_model_calls_per_run),
            timeout_sec=min(limit.timeout_sec, s.agent_operation_timeout_sec),
        )

    def register_profile(self, profile: OperationalProfile) -> None:
        """Registra ou substitui um perfil operacional.

        Args:
            profile: perfil a registrar.
        """
        self._profiles[profile.work_type] = profile

    def override_limit(self, work_type: str, limit: ProfileLimit) -> None:
        """Sobrepõe o limite de um tipo de trabalho (calibração adaptativa).

        Args:
            work_type: tipo de trabalho.
            limit: novo limite a aplicar.
        """
        self._overrides[work_type] = limit

    def clear_override(self, work_type: str) -> None:
        """Remove a sobreposição de um tipo de trabalho (rollback de calibração)."""
        self._overrides.pop(work_type, None)

    def work_types(self) -> list[str]:
        """Devolve os tipos de trabalho registrados."""
        return sorted(self._profiles.keys())


def create_profile_catalog(settings: Settings) -> ProfileCatalog:
    """Factory para criar o catálogo de perfis operacionais.

    Args:
        settings: configurações do processo.

    Returns:
        Instância de ProfileCatalog.
    """
    return ProfileCatalog(settings)
