"""
Arquivo: src/agent/orchestrator/cognitive_router.py
Nome: cognitive_router.py
Propósito: selecionar o modelo apropriado para cada operação baseado em complexidade, risco e capacidades necessárias.
Responsabilidade: camada de aplicação — roteamento cognitivo adaptativo com escalonamento progressivo.
Componentes: CognitiveRouter, OperationProfile, ModelSelection, ProviderRegistry.
Dependências: agent.providers.base, agent.providers.registry, agent.config, agent.domain.enums.
Observações: não presuma que todo modelo suporta tool calling, JSON estruturado, visão ou contextos extensos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.config import Settings

from agent.providers.base import LLMProvider, ModelProfile, ProviderCapabilities
from agent.providers.registry import ProviderCatalog, ProviderSpec, catalog_for_settings


class OperationComplexity(str, Enum):
    """Complexidade estimada de uma operação."""

    SIMPLE = "simple"  # Leitura única, verificação, resposta direta
    MODERATE = "moderate"  # Inspeção + edição, múltiplos arquivos
    COMPLEX = "complex"  # Decomposição, múltiplas etapas, dependências profundas
    CRITICAL = "critical"  # Alto risco, alterações em sistemas críticos


class OperationRisk(str, Enum):
    """Risco da operação."""

    LOW = "low"  # Somente leitura, sem efeitos colaterais
    MEDIUM = "medium"  # Escrita em arquivos não críticos
    HIGH = "high"  # Escrita em produção, migração, exclusão
    CRITICAL = "critical"  # Sistema crítico, dados sensíveis


class RequiredCapability(str, Enum):
    """Capacidades requeridas pela operação."""

    TOOLS = "tools"  # Chamada de ferramentas
    TOOL_LOOP = "tool_loop"  # Ciclo de inspeção com ferramentas
    STRUCTURED_OUTPUT = "structured_output"  # JSON schema
    VISION = "vision"  # Processamento de imagens
    LONG_CONTEXT = "long_context"  # Contexto > 32k tokens
    STREAMING = "streaming"  # Streaming de tokens


@dataclass
class OperationProfile:
    """Perfil da operação para seleção de modelo."""

    complexity: OperationComplexity = OperationComplexity.SIMPLE
    risk: OperationRisk = OperationRisk.LOW
    required_capabilities: set[RequiredCapability] = field(default_factory=set)
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0
    file_count: int = 0
    dependency_depth: int = 0
    is_first_operation: bool = True
    previous_failures: int = 0
    operation_type: str = "operation"  # plan, operation, verification, final_answer


@dataclass
class ModelScore:
    """Pontuação de um modelo para uma operação."""

    provider_name: str
    model_id: str
    profile: ModelProfile
    capabilities: ProviderCapabilities
    score: float
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ModelSelection:
    """Resultado da seleção de modelo."""

    provider_name: str
    model_id: str
    profile: ModelProfile
    capabilities: ProviderCapabilities
    primary_reason: str
    escalated: bool = False
    escalation_reason: str | None = None


class CognitiveRouter:
    """Roteador cognitivo para seleção adaptativa de modelos.

    Seleciona o modelo mais adequado para cada operação considerando:
    - Complexidade e risco da operação
    - Capacidades requeridas (tools, vision, structured output, etc.)
    - Contexto disponível (tokens, arquivos, dependências)
    - Histórico de sucesso do modelo em operações similares
    - Suporte a escalonamento progressivo
    """

    def __init__(self, settings: Settings) -> None:
        """Cria o roteador com as configurações do processo.

        Args:
            settings: configurações do processo.
        """
        self._settings = settings
        self._catalog: ProviderCatalog | None = None
        self._model_history: dict[str, dict[str, int]] = {}  # provider:model -> {success, total}
        self._load_catalog()

    def _load_catalog(self) -> None:
        """Carrega o catálogo de provedores."""
        try:
            self._catalog = catalog_for_settings(self._settings)
        except Exception:
            self._catalog = ProviderCatalog({})

    def _get_available_providers(self) -> list[tuple[str, LLMProvider, ProviderSpec]]:
        """Obtém provedores disponíveis com suas specs."""
        if self._catalog is None:
            return []
        providers = []
        for name in self._catalog.names():
            spec = self._catalog.get(name)
            if spec is None:
                continue
            try:
                provider = self._catalog.build(name, self._settings)
                providers.append((name, provider, spec))
            except Exception:
                continue
        return providers

    def analyze_operation(
        self,
        task_metadata: dict[str, Any],
        operation_type: str,
        context_info: dict[str, Any] | None = None,
    ) -> OperationProfile:
        """Analisa a operação e cria o perfil para seleção.

        Args:
            task_metadata: metadados da tarefa (contém verificação, ferramentas, etc.).
            operation_type: tipo da operação (plan, operation, verification, final_answer).
            context_info: informações adicionais do contexto (arquivos, dependências).

        Returns:
            O perfil da operação.
        """
        context_info = context_info or {}
        meta = task_metadata or {}

        # Determina complexidade
        complexity = self._determine_complexity(meta, context_info)

        # Determina risco
        risk = self._determine_risk(meta, context_info)

        # Determina capacidades requeridas
        required_caps = self._determine_required_capabilities(meta, operation_type)

        # Estima tokens
        est_input = context_info.get("estimated_input_tokens", 0)
        est_output = context_info.get("estimated_output_tokens", 0)

        # Conta arquivos e profundidade
        file_count = context_info.get("file_count", 0)
        dep_depth = context_info.get("dependency_depth", 0)

        # Verifica falhas anteriores
        prev_failures = len(meta.get("failures") or [])

        return OperationProfile(
            complexity=complexity,
            risk=risk,
            required_capabilities=required_caps,
            estimated_input_tokens=est_input,
            estimated_output_tokens=est_output,
            file_count=file_count,
            dependency_depth=dep_depth,
            previous_failures=prev_failures,
            operation_type=operation_type,
        )

    def _determine_complexity(
        self,
        meta: dict[str, Any],
        context_info: dict[str, Any],
    ) -> OperationComplexity:
        """Determina a complexidade da operação."""
        file_count = context_info.get("file_count", 0)
        dep_depth = context_info.get("dependency_depth", 0)
        has_verification = bool(meta.get("verification"))
        bool(meta.get("tool") or meta.get("model_operation"))
        is_atomic = meta.get("atomic", False)
        read_only = meta.get("read_only", False)

        # Operação somente leitura simples
        if read_only and file_count <= 1 and not has_verification:
            return OperationComplexity.SIMPLE

        # Operação atômica simples
        if is_atomic and file_count <= 1 and not has_verification:
            return OperationComplexity.SIMPLE

        # Operação moderada: poucos arquivos, sem verificação
        if file_count <= 3 and dep_depth <= 1 and not has_verification:
            return OperationComplexity.MODERATE

        # Operação complexa: até 10 arquivos, profundidade moderada
        if file_count <= 10 and dep_depth <= 3:
            return OperationComplexity.COMPLEX

        return OperationComplexity.CRITICAL

    def _determine_risk(
        self,
        meta: dict[str, Any],
        context_info: dict[str, Any],
    ) -> OperationRisk:
        """Determina o risco da operação."""
        read_only = meta.get("read_only", False)
        protect_tests = meta.get("protect_tests", False)
        has_verification = bool(meta.get("verification"))
        has_tools = bool(meta.get("tool") or meta.get("model_operation"))
        file_count = context_info.get("file_count", 0)

        if read_only:
            return OperationRisk.LOW
        if protect_tests or has_verification:
            return OperationRisk.HIGH if file_count > 3 else OperationRisk.MEDIUM
        if has_tools:
            return OperationRisk.HIGH if file_count > 5 else OperationRisk.MEDIUM
        if file_count > 5:
            return OperationRisk.HIGH
        if file_count > 1:
            return OperationRisk.MEDIUM
        return OperationRisk.LOW

    def _determine_required_capabilities(
        self,
        meta: dict[str, Any],
        operation_type: str,
    ) -> set[RequiredCapability]:
        """Determina as capacidades requeridas pela operação."""
        caps = set()
        read_only = meta.get("read_only", False)

        # Operações de leitura não precisam de ferramentas
        if not read_only and (meta.get("tool") or meta.get("model_operation") or operation_type == "operation"):
            caps.add(RequiredCapability.TOOLS)
            if operation_type == "operation":
                caps.add(RequiredCapability.TOOL_LOOP)

        if meta.get("verification") and operation_type != "verification":
            caps.add(RequiredCapability.STRUCTURED_OUTPUT)

        # Verifica se precisa de contexto longo
        if meta.get("context_pressure") == "reduce":
            caps.add(RequiredCapability.LONG_CONTEXT)

        return caps

    def score_models(self, profile: OperationProfile) -> list[ModelScore]:
        """Pontua todos os modelos disponíveis para o perfil da operação.

        Args:
            profile: perfil da operação.

        Returns:
            Lista de modelos pontuados, ordenada do melhor para o pior.
        """
        providers = self._get_available_providers()
        if not providers:
            return []

        scores: list[ModelScore] = []

        for provider_name, provider, spec in providers:
            model_id = spec.model or provider.default_model
            if not model_id:
                continue

            # Obtém perfil e capacidades do modelo
            model_profile = self._get_model_profile(provider, model_id)
            caps = provider.capabilities
            if callable(caps):
                caps = caps()
            capabilities = caps

            # Calcula pontuação base
            score, reasons, warnings = self._calculate_score(profile, model_profile, capabilities, provider_name)

            scores.append(
                ModelScore(
                    provider_name=provider_name,
                    model_id=model_id,
                    profile=model_profile,
                    capabilities=capabilities,
                    score=score,
                    reasons=reasons,
                    warnings=warnings,
                )
            )

        # Ordena por pontuação decrescente
        scores.sort(key=lambda s: s.score, reverse=True)
        return scores

    def _get_model_profile(self, provider: LLMProvider, model_id: str) -> ModelProfile:
        """Obtém o perfil do modelo."""
        # Tenta obter do provedor se suportar
        if hasattr(provider, "get_model_profile"):
            try:
                return provider.get_model_profile(model_id)
            except Exception:
                pass

        # Fallback: perfil genérico baseado nas capacidades do provedor
        caps = provider.capabilities
        if callable(caps):
            caps = caps()
        return ModelProfile(
            model_id=model_id,
            context_limit=8192,
            input_budget=6000,
            output_reserve=1024,
            supports_tools=caps.tools,
            supports_vision=caps.vision,
        )

    def _calculate_score(
        self,
        op_profile: OperationProfile,
        model_profile: ModelProfile,
        capabilities: ProviderCapabilities,
        provider_name: str,
    ) -> tuple[float, list[str], list[str]]:
        """Calcula a pontuação de um modelo para a operação."""
        score = 0.0
        reasons = []
        warnings = []

        # Penaliza se não tem capacidades requeridas
        for cap in op_profile.required_capabilities:
            if cap == RequiredCapability.TOOLS and not capabilities.tools:
                score -= 50
                warnings.append("sem suporte a ferramentas")
            elif cap == RequiredCapability.TOOL_LOOP and not capabilities.tool_loop:
                score -= 30
                warnings.append("sem suporte a ciclo de ferramentas")
            elif cap == RequiredCapability.STRUCTURED_OUTPUT and not capabilities.structured_output:
                score -= 20
                warnings.append("sem saída estruturada nativa")
            elif cap == RequiredCapability.VISION and not capabilities.vision:
                score -= 40
                warnings.append("sem suporte a visão")
            elif cap == RequiredCapability.LONG_CONTEXT and model_profile.context_limit < 32768:
                score -= 25
                warnings.append(f"contexto limitado ({model_profile.context_limit} tokens)")
            else:
                score += 10
                reasons.append(f"suporta {cap.value}")

        # Bonifica por suporte a ferramentas se necessário
        if (
            op_profile.required_capabilities
            and RequiredCapability.TOOLS in op_profile.required_capabilities
            and capabilities.tools
            and capabilities.tool_loop
        ):
            score += 30
            reasons.append("ciclo completo de ferramentas")

        # Penaliza por contexto insuficiente
        required_input = op_profile.estimated_input_tokens
        if required_input > 0 and required_input > model_profile.input_budget:
            deficit = required_input - model_profile.input_budget
            score -= min(50, deficit / 100)
            warnings.append(
                f"orçamento de entrada insuficiente (precisa {required_input}, tem {model_profile.input_budget})"
            )

        # Ajusta por complexidade
        complexity_bonus = {
            OperationComplexity.SIMPLE: 0,
            OperationComplexity.MODERATE: 10,
            OperationComplexity.COMPLEX: 20,
            OperationComplexity.CRITICAL: 30,
        }
        score += complexity_bonus[op_profile.complexity]

        # Penaliza por risco alto com modelo sem ferramentas
        if op_profile.risk in {OperationRisk.HIGH, OperationRisk.CRITICAL} and not capabilities.tools:
            score -= 40
            warnings.append("risco alto sem ferramentas")

        # Bonifica por histórico de sucesso
        history_key = f"{provider_name}:{model_profile.model_id}"
        history = self._model_history.get(history_key, {"success": 0, "total": 0})
        if history["total"] > 0:
            success_rate = history["success"] / history["total"]
            score += success_rate * 20
            reasons.append(f"taxa de sucesso histórica: {success_rate:.0%}")

        # Penaliza se é modelo local mas operação precisa de capacidades avançadas
        is_local = provider_name in {"ollama", "llamacpp", "meu_ollama"}
        if is_local and op_profile.complexity == OperationComplexity.CRITICAL:
            score -= 15
            warnings.append("modelo local para operação crítica")

        return max(0, score), reasons, warnings

    def select_model(self, profile: OperationProfile) -> ModelSelection | None:
        """Seleciona o melhor modelo para a operação.

        Args:
            profile: perfil da operação.

        Returns:
            A seleção do modelo, ou None se nenhum modelo adequado.
        """
        scores = self.score_models(profile)
        if not scores:
            return None

        best = scores[0]
        if best.score <= 0:
            return None

        # Verifica se precisa escalonar
        escalated = False
        escalation_reason = None
        history_key = f"{best.provider_name}:{best.model_id}"
        history = self._model_history.get(history_key, {"success": 0, "total": 0})

        # Escalona se modelo local falhou antes em operação similar
        if (
            history["total"] > 0
            and history["success"] / history["total"] < 0.5
            and profile.complexity in {OperationComplexity.COMPLEX, OperationComplexity.CRITICAL}
        ):
            # Tenta achar um modelo não-local
                best = next(
                    (
                        s
                        for s in scores[1:]
                        if not s.warnings or "modelo local" not in " ".join(s.warnings)
                    ),
                    None,
                )
                if best is not None:
                    escalated = True
                    escalation_reason = (
                        f"modelo local {history_key} com taxa de sucesso baixa "
                        f"({history['success']}/{history['total']})"
                    )

        return ModelSelection(
            provider_name=best.provider_name,
            model_id=best.model_id,
            profile=best.profile,
            capabilities=best.capabilities,
            primary_reason=best.reasons[0] if best.reasons else "melhor pontuação",
            escalated=escalated,
            escalation_reason=escalation_reason,
        )

    def record_result(
        self,
        provider_name: str,
        model_id: str,
        success: bool,
    ) -> None:
        """Registra o resultado de uma operação para aprendizado.

        Args:
            provider_name: nome do provedor.
            model_id: identificador do modelo.
            success: se a operação foi bem-sucedida.
        """
        key = f"{provider_name}:{model_id}"
        history = self._model_history.get(key, {"success": 0, "total": 0})
        history["total"] += 1
        if success:
            history["success"] += 1
        self._model_history[key] = history

    def get_provider_for_selection(self, selection: ModelSelection) -> LLMProvider | None:
        """Obtém a instância do provedor para a seleção.

        Args:
            selection: seleção do modelo.

        Returns:
            Instância do provedor, ou None se não disponível.
        """
        if self._catalog is None:
            return None
        try:
            return self._catalog.build(selection.provider_name, self._settings)
        except Exception:
            return None


def create_cognitive_router(settings: Settings) -> CognitiveRouter:
    """Factory para criar o roteador cognitivo.

    Args:
        settings: configurações do processo.

    Returns:
        Instância do CognitiveRouter.
    """
    return CognitiveRouter(settings)
