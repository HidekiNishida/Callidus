# Knowledge Engine

**Propósito:** Subsistema de aquisição, processamento, armazenamento e reutilização de conhecimento externo para agentes do Callidus.

---

## Estrutura

```text
knowledge/
├── __init__.py              # API pública
├── models.py                # Enums + reexport modelos SQLAlchemy
├── request.py               # KnowledgeDiscovery, KnowledgeRequest, KnowledgeGap
├── service.py               # KnowledgeEngineService (orquestrador central)
├── tools.py                 # Ferramentas do modelo (search, acquire, save, validate, reuser)
├── providers/
│   ├── __init__.py          # Exports: SearchProvider, DuckDuckGo, GitHub, Documentation
│   ├── base.py              # SearchProvider (ABC), SearchResult, SearchProviderError
│   ├── duckduckgo.py        # DuckDuckGoProvider (HTML scraping)
│   ├── github.py            # GitHubProvider (REST API)
│   └── docs.py              # DocumentationProvider (site: filter)
├── browser/
│   ├── __init__.py          # Exports: BrowserSession, AIServiceManager, etc.
│   ├── session.py           # BrowserSession (Playwright persistente)
│   ├── ai_services.py       # AIServiceManager (ChatGPT, Gemini, Claude)
│   └── extraction.py        # ContentExtractor (extração semântica)
├── processing/
│   ├── __init__.py          # Exports: normalize, compare, synthesize, verify
│   ├── normalize.py         # ResultNormalizer, NormalizedSource
│   ├── compare.py           # SourceComparator, ComparisonResult
│   ├── synthesize.py        # KnowledgeSynthesizer, SynthesisResult
│   └── verify.py            # CodeVerifier, DocVerifier, VersionChecker
├── memory/
│   ├── __init__.py          # Exports: store, reuse
│   ├── store.py             # KnowledgeMemoryStore (SQLite + FTS5)
│   └── reuse.py             # KnowledgeReuser, ContextualRetriever, BudgetAwareInjector
├── learning/
│   ├── __init__.py          # Exports: confidence, tracker
│   ├── confidence.py        # ConfidenceScorer, ConfidenceUpdater
│   └── tracker.py           # LearningTracker, PatternDetector, ImprovementSuggester
├── reliability/
│   ├── __init__.py          # Exports: circuit_breaker, retry, limits, recovery, security
│   ├── circuit_breaker.py   # CircuitBreaker, CircuitBreakerRegistry
│   ├── retry.py             # RetryPolicy, retry_async/sync, TimeoutManager
│   ├── limits.py            # ResourceLimits, ConcurrencyLimiter, StorageQuota, ResourceLimiter
│   ├── recovery.py          # CheckpointManager, RecoveryManager, auto_recover_on_startup
│   └── security.py          # InputSanitizer, CredentialManager, AccessControl, AuditLogger
└── tools.py                 # Registro de ferramentas no ToolRegistry
```

---

## Modelos de Dados (SQLite)

### Tabelas

| Tabela | Descrição |
|--------|-----------|
| `knowledge_items` | Itens de conhecimento (title, content, kind, technology, confidence, validation_status) |
| `knowledge_sources` | Fontes (source_kind, url, credibility, raw_content) |
| `knowledge_requests` | Solicitações de aquisição |
| `knowledge_validations` | Validações (passed, method, evidence) |
| `knowledge_relations` | Relações entre itens |
| `knowledge_usage` | Histórico de uso |
| `knowledge_versions` | Versionamento |
| `knowledge_items_fts` | Índice FTS5 para busca full-text |

---

## Ferramentas do Modelo

| Ferramenta | Descrição |
|------------|-----------|
| `search_knowledge` | Busca com filtros (query, kind, technology, version, min_confidence, limit) |
| `get_knowledge` | Detalhes completos (conteúdo, fontes, validações) |
| `acquire_knowledge` | Aquisição externa (provedores, depth, max_time) |
| `save_knowledge` | Salva descoberta manual |
| `validate_knowledge` | Validação com evidências |
| `reuser_knowledge` | Recuperação contextual com orçamento de tokens |
| `knowledge_stats` | Estatísticas do projeto |

---

## Fluxo Principal

```text
Agente → Orchestrator → KnowledgeEngineService
    → KnowledgeDiscovery.should_acquire()
    → create_request() → acquire_knowledge() [providers paralelos]
    → normalize → compare → synthesize → verify
    → save_knowledge() → KnowledgeMemoryStore
    → KnowledgeReuser.prepare_context_for_task() → BudgetAwareInjector
    → formatted_knowledge → injeção no prompt
```

---

## Configuração

```python
# ResourceLimits personalizados
limits = ResourceLimits(
    max_concurrent_searches=5,
    max_storage_mb=1000,
    max_context_tokens=8000,
)
limiter = ResourceLimiter(limits, storage_root=Path("data/knowledge"))
```

---

## Testes

```bash
# Testes do Knowledge Engine
pytest tests/test_knowledge_engine.py tests/test_knowledge_providers.py tests/test_knowledge_processing.py tests/test_knowledge_memory.py -v

# Suite completa
pytest tests/ -v
```

---

## Documentação Relacionada

- [Architecture Overview](../../../docs/architecture/knowledge-engine.md)
- [Database Schema](../../../docs/architecture/modelo-dados.md)
- [Providers](../../../docs/architecture/provedores.md)