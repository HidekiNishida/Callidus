"""
Arquivo: tests/test_cognitive_router.py
Nome: test_cognitive_router.py
Propósito: testar o roteador cognitivo de seleção de modelos.
Responsabilidade: camada de testes — seleção baseada em complexidade, risco, capacidades e histórico.
Componentes: análise de operação, pontuação de modelos, seleção, escalonamento, registro de resultado.
Dependências: agent.orchestrator.cognitive_router, agent.config, pytest.
Observações: usa provedor mock para isolar a lógica do roteador.
"""

import pytest

from agent.config import Settings
from agent.orchestrator.cognitive_router import (
    CognitiveRouter,
    ModelSelection,
    OperationComplexity,
    OperationProfile,
    OperationRisk,
    RequiredCapability,
    create_cognitive_router,
)
from agent.providers.base import LLMProvider, ModelProfile, ProviderCapabilities
from agent.providers.registry import ProviderSpec


class MockProvider(LLMProvider):
    """Provedor mock para testes."""

    name = "mock"
    supports_streaming = False
    default_model = "mock-model"

    def __init__(self, capabilities: ProviderCapabilities | None = None):
        self.capabilities = capabilities or ProviderCapabilities()
        self._model_profiles = {}

    async def _chat(self, request):
        raise NotImplementedError()

    async def _stream(self, request):
        raise NotImplementedError()

    async def chat(self, request):
        raise NotImplementedError()

    async def stream(self, request):
        raise NotImplementedError()

    def list_models(self):
        return ["mock-model"]

    def get_model_profile(self, model_id: str) -> ModelProfile:
        return self._model_profiles.get(
            model_id,
            ModelProfile(
                model_id=model_id,
                context_limit=8192,
                input_budget=6000,
                output_reserve=1024,
                supports_tools=self.capabilities.tools,
                supports_vision=self.capabilities.vision,
            ),
        )


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path)


@pytest.fixture
def mock_catalog(settings, monkeypatch):
    """Cria um catálogo mock com provedores de teste."""
    from agent.providers.registry import ProviderCatalog

    # Provedor local (Ollama-like) - sem ferramentas
    local_caps = ProviderCapabilities(streaming=True, model_listing=True)
    local_provider = MockProvider(local_caps)
    local_spec = ProviderSpec(type="ollama", model="local-model", base_url="http://localhost:11434")

    # Provedor com ferramentas
    tool_caps = ProviderCapabilities(
        streaming=True,
        tools=True,
        tool_loop=True,
        structured_output=True,
        model_listing=True,
    )
    tool_provider = MockProvider(tool_caps)
    tool_spec = ProviderSpec(type="openai_compatible", model="gpt-4", base_url="https://api.openai.com/v1")

    # Provedor com visão
    vision_caps = ProviderCapabilities(
        streaming=True,
        tools=True,
        tool_loop=True,
        structured_output=True,
        vision=True,
        model_listing=True,
    )
    vision_provider = MockProvider(vision_caps)
    vision_spec = ProviderSpec(type="openai_compatible", model="gpt-4-vision", base_url="https://api.openai.com/v1")

    catalog = ProviderCatalog(
        {
            "local": local_spec,
            "tools": tool_spec,
            "vision": vision_spec,
        }
    )

    # Mock do build para retornar nossos provedores
    def mock_build(name, settings):
        if name == "local":
            return local_provider
        elif name == "tools":
            return tool_provider
        elif name == "vision":
            return vision_provider
        raise ValueError(f"Unknown provider: {name}")

    # Patch no nível do módulo onde catalog_for_settings é usado
    import agent.orchestrator.cognitive_router as cr_module

    monkeypatch.setattr(cr_module, "catalog_for_settings", lambda s: catalog)
    monkeypatch.setattr(catalog, "build", mock_build)

    return catalog
    monkeypatch.setattr("agent.orchestrator.cognitive_router.catalog_for_settings", lambda s: catalog)

    return catalog


def test_analyze_simple_operation(settings, mock_catalog):
    """Operação simples de leitura deve ter complexidade baixa."""
    router = CognitiveRouter(settings)

    meta = {"read_only": True}
    profile = router.analyze_operation(meta, "operation", {"file_count": 1})

    assert profile.complexity == OperationComplexity.SIMPLE
    assert profile.risk == OperationRisk.LOW
    assert RequiredCapability.TOOLS not in profile.required_capabilities


def test_analyze_moderate_operation(settings, mock_catalog):
    """Operação com edição de poucos arquivos."""
    router = CognitiveRouter(settings)

    meta = {"model_operation": True, "atomic": True}
    profile = router.analyze_operation(meta, "operation", {"file_count": 2, "dependency_depth": 1})

    assert profile.complexity == OperationComplexity.MODERATE
    assert profile.risk == OperationRisk.MEDIUM
    assert RequiredCapability.TOOLS in profile.required_capabilities
    assert RequiredCapability.TOOL_LOOP in profile.required_capabilities


def test_analyze_complex_operation(settings, mock_catalog):
    """Operação complexa com muitos arquivos e verificação."""
    router = CognitiveRouter(settings)

    meta = {"model_operation": True, "verification": {"type": "pytest"}}
    profile = router.analyze_operation(meta, "operation", {"file_count": 8, "dependency_depth": 3})

    assert profile.complexity == OperationComplexity.COMPLEX
    assert profile.risk == OperationRisk.HIGH
    assert RequiredCapability.STRUCTURED_OUTPUT in profile.required_capabilities


def test_analyze_critical_operation(settings, mock_catalog):
    """Operação crítica com muitos arquivos e dependências profundas."""
    router = CognitiveRouter(settings)

    meta = {"model_operation": True, "verification": {"type": "pytest"}}
    profile = router.analyze_operation(meta, "operation", {"file_count": 20, "dependency_depth": 5})

    assert profile.complexity == OperationComplexity.CRITICAL
    assert profile.risk == OperationRisk.HIGH


def test_analyze_verification_operation(settings, mock_catalog):
    """Operação de verificação não precisa de tool_loop."""
    router = CognitiveRouter(settings)

    meta = {"verification": {"type": "pytest"}}
    profile = router.analyze_operation(meta, "verification", {})

    assert RequiredCapability.TOOLS not in profile.required_capabilities
    assert RequiredCapability.TOOL_LOOP not in profile.required_capabilities


def test_score_models_prefers_tool_capable(settings, mock_catalog):
    """Modelos com ferramentas devem pontuar mais para operações que precisam."""
    router = CognitiveRouter(settings)

    profile = OperationProfile(
        complexity=OperationComplexity.MODERATE,
        risk=OperationRisk.MEDIUM,
        required_capabilities={RequiredCapability.TOOLS, RequiredCapability.TOOL_LOOP},
        estimated_input_tokens=2000,
        estimated_output_tokens=1000,
    )

    scores = router.score_models(profile)
    assert len(scores) == 3

    # Provedor com ferramentas deve pontuar mais alto
    best = scores[0]
    assert best.provider_name in {"tools", "vision"}
    assert best.capabilities.tools is True
    assert best.capabilities.tool_loop is True


def test_score_models_penalizes_missing_capabilities(settings, mock_catalog):
    """Modelos sem capacidades requeridas são penalizados."""
    router = CognitiveRouter(settings)

    profile = OperationProfile(
        complexity=OperationComplexity.COMPLEX,
        risk=OperationRisk.HIGH,
        required_capabilities={RequiredCapability.VISION},
    )

    scores = router.score_models(profile)

    # Provedor com visão deve ser o melhor
    best = scores[0]
    assert best.provider_name == "vision"
    assert best.capabilities.vision is True

    # Provedor local deve ser penalizado
    local_score = next(s for s in scores if s.provider_name == "local")
    assert local_score.score < best.score


def test_select_model_returns_best(settings, mock_catalog):
    """Seleção retorna o melhor modelo."""
    router = CognitiveRouter(settings)

    profile = OperationProfile(
        complexity=OperationComplexity.MODERATE,
        risk=OperationRisk.MEDIUM,
        required_capabilities={RequiredCapability.TOOLS},
    )

    selection = router.select_model(profile)
    assert selection is not None
    assert selection.provider_name in {"tools", "vision"}
    assert selection.primary_reason


def test_escalation_on_low_success_rate(settings, mock_catalog):
    """Escalona para modelo melhor quando taxa de sucesso é baixa."""
    router = CognitiveRouter(settings)

    # Registra histórico ruim para o modelo com ferramentas
    router.record_result("tools", "gpt-4", False)
    router.record_result("tools", "gpt-4", False)
    router.record_result("tools", "gpt-4", False)

    profile = OperationProfile(
        complexity=OperationComplexity.COMPLEX,
        risk=OperationRisk.HIGH,
        required_capabilities={RequiredCapability.TOOLS},
    )

    selection = router.select_model(profile)
    assert selection is not None
    # Deve escalar para vision (que também tem ferramentas mas não é "local")
    assert selection.escalated is True
    assert "taxa de sucesso baixa" in selection.escalation_reason


def test_record_result_updates_history(settings, mock_catalog):
    """Registro de resultado atualiza histórico."""
    router = CognitiveRouter(settings)

    router.record_result("local", "local-model", True)
    router.record_result("local", "local-model", False)
    router.record_result("local", "local-model", True)

    history = router._model_history["local:local-model"]
    assert history["total"] == 3
    assert history["success"] == 2


def test_get_provider_for_selection(settings, mock_catalog):
    """Obtém provedor para a seleção."""
    router = CognitiveRouter(settings)

    selection = ModelSelection(
        provider_name="tools",
        model_id="gpt-4",
        profile=ModelProfile(model_id="gpt-4"),
        capabilities=ProviderCapabilities(tools=True),
        primary_reason="test",
    )

    provider = router.get_provider_for_selection(selection)
    assert provider is not None
    assert provider.capabilities.tools is True


def test_factory_function(settings, mock_catalog):
    """Factory function cria o roteador."""
    router = create_cognitive_router(settings)
    assert isinstance(router, CognitiveRouter)


def test_high_risk_requires_tools(settings, mock_catalog):
    """Operação de alto risco sem ferramentas é penalizada."""
    router = CognitiveRouter(settings)

    profile = OperationProfile(
        complexity=OperationComplexity.MODERATE,
        risk=OperationRisk.HIGH,
        required_capabilities=set(),
    )

    scores = router.score_models(profile)

    # Modelo sem ferramentas deve ter warning
    local_score = next(s for s in scores if s.provider_name == "local")
    assert any("risco alto sem ferramentas" in w for w in local_score.warnings)


def test_long_context_capability(settings, mock_catalog):
    """Operação que precisa de contexto longo penaliza modelos com contexto pequeno."""
    router = CognitiveRouter(settings)

    profile = OperationProfile(
        complexity=OperationComplexity.MODERATE,
        risk=OperationRisk.MEDIUM,
        required_capabilities={RequiredCapability.LONG_CONTEXT},
        estimated_input_tokens=50000,
    )

    scores = router.score_models(profile)

    # Modelo local tem contexto 8192, deve ser penalizado
    local_score = next(s for s in scores if s.provider_name == "local")
    assert any("contexto limitado" in w for w in local_score.warnings)


def test_no_models_returns_none(settings, mock_catalog):
    """Sem modelos disponíveis retorna None."""
    from agent.providers.registry import ProviderCatalog

    empty_catalog = ProviderCatalog({})

    import agent.orchestrator.cognitive_router as cr_module

    original = cr_module.catalog_for_settings
    cr_module.catalog_for_settings = lambda s: empty_catalog

    try:
        router = CognitiveRouter(settings)
        profile = OperationProfile(required_capabilities={RequiredCapability.TOOLS})
        selection = router.select_model(profile)
        assert selection is None
    finally:
        cr_module.catalog_for_settings = original
