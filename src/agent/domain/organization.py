"""
Arquivo: src/agent/domain/organization.py
Nome: organization.py
Propósito: catálogo da organização de engenharia — escritórios, equipes, papéis, especialidades e propriedade dos módulos — e a seleção determinística do responsável por uma tarefa.
Responsabilidade: camada de domínio — vocabulário organizacional e regra de atribuição, sem I/O.
Componentes: Team, Role, Specialty, OwnershipRule, Assignment, OFFICES, TEAMS, ROLES, SPECIALTIES, OWNERSHIP, owner_of, select_assignment, validate_catalog, reviewer_allowed.
Dependências: dataclasses, re (stdlib).
Observações: papel não é hierarquia — `orchestrator`/`lead`/`worker` continuam dizendo onde o agente está na árvore; o papel diz o que ele sabe fazer e quem revisa. A seleção não usa inferência.

Por que existe
--------------
O agente lógico já existe (um por tarefa) e a especialidade já existe como skill da estratégia
(`ProfessionalStrategy.lead_specialty`). Faltava a dimensão organizacional: qual equipe é dona
do código tocado, qual papel executa, qual papel **diferente** revisa e quando a mudança precisa
de coordenação com o arquiteto. Isto é dado puro — o serviço de organização grava o resultado
no `metadata_json` da tarefa e do agente.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ------------------------------------------------------------------ catálogo


@dataclass(frozen=True)
class Team:
    """Equipe ou escritório: grupo de papéis com uma missão e uma área de código."""

    id: str
    name: str
    office: str
    mission: str


@dataclass(frozen=True)
class Specialty:
    """Competência técnica. `skill_id` liga a competência a uma skill de `skills/`."""

    id: str
    name: str
    skill_id: str


@dataclass(frozen=True)
class Role:
    """Papel profissional que um agente lógico (ou o humano) pode assumir.

    Atributos:
        id: identificador estável (usado na API e nos documentos `docs/engineering/roles/`).
        name: nome legível.
        team: equipe a que o papel pertence.
        mission: uma frase sobre para que o papel existe.
        specialties: competências que o papel traz.
        reviews: papéis cujo trabalho este papel pode aprovar.
        authority: decisões que o papel pode tomar sozinho.
        escalates_to: papel acionado quando a decisão passa da autoridade.
        human: `True` quando só uma pessoa pode exercer o papel.
    """

    id: str
    name: str
    team: str
    mission: str
    specialties: tuple[str, ...] = ()
    reviews: tuple[str, ...] = ()
    authority: tuple[str, ...] = ()
    escalates_to: str | None = None
    human: bool = False


@dataclass(frozen=True)
class OwnershipRule:
    """Regra de propriedade de um caminho.

    `pattern` é um prefixo de caminho relativo à raiz (termina em `/` para pasta), um nome de
    pasta em qualquer nível (`seg:tests`) ou uma extensão (`ext:.py`). A regra mais específica
    vence; cada regra tem **um** dono principal. `coordination` nomeia o papel que precisa
    concordar quando a mudança toca a área (contrato compartilhado ou área protegida).
    """

    pattern: str
    team: str
    role: str
    specialty: str
    protected: bool = False
    shared_contract: bool = False
    coordination: str | None = None


OFFICES: dict[str, str] = {
    "direction": "Direção",
    "product": "Product Office",
    "architecture": "Architecture Office",
    "engineering": "Engineering Teams",
    "quality": "Quality Office",
    "knowledge": "Knowledge Office",
    "release": "Release Office",
}

TEAMS: dict[str, Team] = {
    t.id: t
    for t in (
        Team("direction", "Direção", "direction", "objetivos, prioridades e coerência técnica global"),
        Team("product_office", "Product Office", "product", "transformar pedidos em requisitos verificáveis e planos"),
        Team("architecture_office", "Architecture Office", "architecture", "fronteiras, contratos e decisões estruturais"),
        Team("core_engineering", "Core Engineering", "engineering", "domínio, serviços e persistência"),
        Team("ai_agent_engineering", "AI/Agent Engineering", "engineering", "orquestração, decomposição e operação do modelo"),
        Team("knowledge_engineering", "Knowledge Engineering", "engineering", "contexto, memória, conhecimento e skills"),
        Team("integrations_engineering", "Integrations Engineering", "engineering", "provedores, ferramentas, MCP, remoto e automação"),
        Team("product_experience", "Product Experience", "engineering", "API HTTP e interface"),
        Team("quality_engineering", "Quality Engineering", "quality", "verificação, testes, segurança, avaliação e métricas"),
        Team("knowledge_office", "Knowledge Office", "knowledge", "documentação normativa e técnica"),
        Team("release_office", "Release Office", "release", "integração, CI e publicação"),
    )
}

SPECIALTIES: dict[str, Specialty] = {
    s.id: s
    for s in (
        Specialty("software_engineering", "Engenharia de software", "software_engineering"),
        Specialty("system_architecture", "Arquitetura de sistemas", "system_architecture"),
        Specialty("testing_quality_assurance", "Testes e QA", "testing_quality_assurance"),
        Specialty("debugging_root_cause", "Depuração e causa raiz", "debugging_root_cause"),
        Specialty("refactoring_clean_code", "Refatoração", "refactoring_clean_code"),
        Specialty("technical_writing", "Escrita técnica", "technical_writing"),
        Specialty("domain_engineering", "Modelagem de domínio", "system_architecture"),
        Specialty("data_engineering", "Persistência e dados", "software_engineering"),
        Specialty("agent_orchestration", "Orquestração de agentes", "system_architecture"),
        Specialty("llm_integration", "Integração de modelos", "software_engineering"),
        Specialty("tool_engineering", "Ferramentas do agente", "software_engineering"),
        Specialty("knowledge_retrieval", "Recuperação de conhecimento", "software_engineering"),
        Specialty("api_engineering", "API HTTP", "software_engineering"),
        Specialty("frontend", "Interface web", "software_engineering"),
        Specialty("verification", "Verificação", "testing_quality_assurance"),
        Specialty("security", "Segurança", "testing_quality_assurance"),
        Specialty("analytics", "Métricas e avaliação", "testing_quality_assurance"),
        Specialty("release", "Integração e entrega", "software_engineering"),
    )
}

_DEV_REVIEWERS = ("qa_engineer", "reviewer")

ROLES: dict[str, Role] = {
    r.id: r
    for r in (
        Role("product_owner", "Product Owner", "direction", "decide objetivos, escopo e o que exige autorização humana",
             authority=("escopo do produto", "critérios de estágio", "modelo e provedor padrão", "licença e versão"),
             reviews=("cto", "planner", "requirements_analyst"), human=True),
        Role("cto", "CTO", "direction", "coerência arquitetural, qualidade global e conflitos entre especialidades",
             specialties=("system_architecture",), reviews=("software_architect", "solutions_architect", "tech_lead",
                                                            "release_engineer", "knowledge_steward"),
             authority=("contratos públicos", "regras normativas", "critérios de avaliação"), escalates_to="product_owner"),
        Role("software_architect", "Arquiteto de software", "architecture_office",
             "fronteiras de camada, contratos e ADRs", specialties=("system_architecture", "domain_engineering"),
             reviews=("backend_developer", "ai_engineer", "knowledge_engineer", "frontend_developer", "tech_lead"),
             authority=("mudança em contrato compartilhado com migração", "novo padrão de projeto"), escalates_to="cto"),
        Role("solutions_architect", "Arquiteto de soluções", "architecture_office",
             "desenho da solução que cruza vários módulos", specialties=("system_architecture", "data_engineering"),
             reviews=("planner",), authority=("divisão da solução entre equipes",), escalates_to="software_architect"),
        Role("requirements_analyst", "Analista de requisitos", "product_office",
             "requisitos verificáveis e critérios de aceite", specialties=("technical_writing",),
             authority=("redação de requisitos",), escalates_to="product_owner"),
        Role("planner", "Planejador", "product_office", "plano, dependências e ordem de execução",
             specialties=("system_architecture",), authority=("ordem das etapas",), escalates_to="solutions_architect"),
        Role("tech_lead", "Tech lead", "core_engineering", "coordena especialistas de uma entrega e integra as partes",
             specialties=("software_engineering", "system_architecture"),
             reviews=("backend_developer", "frontend_developer", "ai_engineer", "knowledge_engineer"),
             authority=("distribuição entre especialistas", "decomposição"), escalates_to="software_architect"),
        Role("backend_developer", "Desenvolvedor backend", "core_engineering", "serviços, persistência e ferramentas",
             specialties=("software_engineering", "data_engineering", "debugging_root_cause"),
             authority=("implementação dentro do escopo",), escalates_to="tech_lead"),
        Role("frontend_developer", "Desenvolvedor frontend", "product_experience", "interface Vue, estilo e acessibilidade",
             specialties=("frontend",), authority=("implementação dentro do escopo",), escalates_to="tech_lead"),
        Role("ai_engineer", "Engenheiro de IA", "ai_agent_engineering", "orquestração, prompts, provedores e decomposição",
             specialties=("agent_orchestration", "llm_integration"), authority=("implementação dentro do escopo",),
             escalates_to="tech_lead"),
        Role("knowledge_engineer", "Engenheiro de conhecimento", "knowledge_engineering",
             "contexto, memória, grafo e skills", specialties=("knowledge_retrieval",),
             authority=("implementação dentro do escopo",), escalates_to="tech_lead"),
        Role("qa_engineer", "QA engineer", "quality_engineering", "confere evidências e reprova o que não está comprovado",
             specialties=("testing_quality_assurance", "verification"),
             reviews=("backend_developer", "frontend_developer", "ai_engineer", "knowledge_engineer", "test_engineer",
                      "tech_lead"),
             authority=("reprovar entrega sem evidência",), escalates_to="cto"),
        Role("test_engineer", "Test engineer", "quality_engineering", "testes determinísticos e cenários de avaliação",
             specialties=("testing_quality_assurance", "analytics"), authority=("criar e ajustar testes",),
             escalates_to="qa_engineer"),
        Role("reviewer", "Code reviewer", "quality_engineering", "revisão de código: coesão, acoplamento, legibilidade",
             specialties=("refactoring_clean_code", "software_engineering"),
             reviews=("backend_developer", "frontend_developer", "ai_engineer", "knowledge_engineer", "test_engineer",
                      "knowledge_steward", "release_engineer", "tech_lead"),
             authority=("pedir mudança antes da integração",), escalates_to="software_architect"),
        Role("security_engineer", "Security engineer", "quality_engineering", "permissões, segredos e caminhos perigosos",
             specialties=("security",), reviews=("backend_developer", "ai_engineer", "frontend_developer"),
             authority=("bloquear mudança insegura",), escalates_to="cto"),
        Role("knowledge_steward", "Knowledge steward", "knowledge_office",
             "documentação canônica, ADRs e o resume.md em dia", specialties=("technical_writing",),
             reviews=("requirements_analyst",), authority=("organização da documentação",), escalates_to="cto"),
        Role("release_engineer", "Release engineer", "release_office", "CI, portões, integração e auditoria final",
             specialties=("release",), authority=("bloquear integração com portão vermelho",), escalates_to="cto"),
    )
}

#: Revisor padrão de cada papel executor. O revisor nunca é o próprio executor.
DEFAULT_REVIEWER: dict[str, str] = {
    "backend_developer": "qa_engineer",
    "frontend_developer": "qa_engineer",
    "ai_engineer": "qa_engineer",
    "knowledge_engineer": "qa_engineer",
    "tech_lead": "qa_engineer",
    "test_engineer": "reviewer",
    "knowledge_steward": "reviewer",
    "release_engineer": "reviewer",
    "software_architect": "cto",
    "solutions_architect": "software_architect",
    "planner": "solutions_architect",
    "requirements_analyst": "product_owner",
    "qa_engineer": "cto",
    "reviewer": "software_architect",
    "security_engineer": "cto",
    "cto": "product_owner",
}

#: Propriedade do repositório do Callidus (prefixos) e regras genéricas para qualquer projeto.
OWNERSHIP: tuple[OwnershipRule, ...] = (
    OwnershipRule("src/agent/domain/", "core_engineering", "backend_developer", "domain_engineering",
                  shared_contract=True, coordination="software_architect"),
    OwnershipRule("src/agent/domain/state_machine.py", "core_engineering", "backend_developer", "domain_engineering",
                  protected=True, shared_contract=True, coordination="software_architect"),
    OwnershipRule("src/agent/services/", "core_engineering", "backend_developer", "software_engineering"),
    OwnershipRule("src/agent/persistence/", "core_engineering", "backend_developer", "data_engineering",
                  protected=True, shared_contract=True, coordination="software_architect"),
    OwnershipRule("src/agent/config.py", "core_engineering", "backend_developer", "software_engineering",
                  protected=True, shared_contract=True, coordination="product_owner"),
    OwnershipRule("src/agent/orchestrator/", "ai_agent_engineering", "ai_engineer", "agent_orchestration"),
    OwnershipRule("src/agent/context/", "knowledge_engineering", "knowledge_engineer", "knowledge_retrieval"),
    OwnershipRule("src/agent/knowledge/", "knowledge_engineering", "knowledge_engineer", "knowledge_retrieval"),
    OwnershipRule("src/agent/memory/", "knowledge_engineering", "knowledge_engineer", "knowledge_retrieval"),
    OwnershipRule("src/agent/skills/", "knowledge_engineering", "knowledge_engineer", "knowledge_retrieval"),
    OwnershipRule("skills/", "knowledge_engineering", "knowledge_engineer", "technical_writing"),
    OwnershipRule("src/agent/providers/", "integrations_engineering", "ai_engineer", "llm_integration"),
    OwnershipRule("src/agent/tools/", "integrations_engineering", "backend_developer", "tool_engineering"),
    OwnershipRule("src/agent/mcp/", "integrations_engineering", "backend_developer", "tool_engineering"),
    OwnershipRule("src/agent/remote/", "integrations_engineering", "backend_developer", "tool_engineering"),
    OwnershipRule("src/agent/automation/", "integrations_engineering", "backend_developer", "tool_engineering"),
    OwnershipRule("src/agent/security/", "quality_engineering", "security_engineer", "security",
                  protected=True, coordination="security_engineer"),
    OwnershipRule("src/agent/verification/", "quality_engineering", "test_engineer", "verification",
                  shared_contract=True, coordination="qa_engineer"),
    OwnershipRule("src/agent/intelligence/", "quality_engineering", "backend_developer", "analytics"),
    OwnershipRule("src/agent/observability/", "quality_engineering", "backend_developer", "analytics",
                  shared_contract=True, coordination="software_architect"),
    OwnershipRule("src/agent/api/", "product_experience", "backend_developer", "api_engineering",
                  shared_contract=True, coordination="software_architect"),
    OwnershipRule("web/static/", "product_experience", "frontend_developer", "frontend"),
    OwnershipRule("tests/", "quality_engineering", "test_engineer", "testing_quality_assurance"),
    OwnershipRule("lab/", "quality_engineering", "test_engineer", "analytics"),
    OwnershipRule("lab/avaliar.py", "quality_engineering", "test_engineer", "analytics",
                  protected=True, coordination="cto"),
    OwnershipRule("AGENTS.md", "knowledge_office", "knowledge_steward", "technical_writing",
                  protected=True, coordination="cto"),
    OwnershipRule("docs/regras/", "knowledge_office", "knowledge_steward", "technical_writing",
                  protected=True, coordination="cto"),
    OwnershipRule("docs/", "knowledge_office", "knowledge_steward", "technical_writing"),
    OwnershipRule("scripts/", "release_office", "release_engineer", "release"),
    OwnershipRule(".github/", "release_office", "release_engineer", "release", protected=True, coordination="cto"),
    OwnershipRule("pyproject.toml", "release_office", "release_engineer", "release",
                  protected=True, coordination="product_owner"),
    OwnershipRule("data/", "direction", "product_owner", "software_engineering", protected=True,
                  coordination="product_owner"),
    # Regras genéricas: valem em qualquer projeto que o Callidus edita.
    OwnershipRule("seg:tests", "quality_engineering", "test_engineer", "testing_quality_assurance"),
    OwnershipRule("seg:test", "quality_engineering", "test_engineer", "testing_quality_assurance"),
    OwnershipRule("seg:docs", "knowledge_office", "knowledge_steward", "technical_writing"),
    OwnershipRule("seg:migrations", "core_engineering", "backend_developer", "data_engineering",
                  protected=True, shared_contract=True, coordination="software_architect"),
    OwnershipRule("seg:.github", "release_office", "release_engineer", "release"),
    OwnershipRule("ext:.md", "knowledge_office", "knowledge_steward", "technical_writing"),
    OwnershipRule("ext:.js", "product_experience", "frontend_developer", "frontend"),
    OwnershipRule("ext:.mjs", "product_experience", "frontend_developer", "frontend"),
    OwnershipRule("ext:.ts", "product_experience", "frontend_developer", "frontend"),
    OwnershipRule("ext:.tsx", "product_experience", "frontend_developer", "frontend"),
    OwnershipRule("ext:.vue", "product_experience", "frontend_developer", "frontend"),
    OwnershipRule("ext:.css", "product_experience", "frontend_developer", "frontend"),
    OwnershipRule("ext:.html", "product_experience", "frontend_developer", "frontend"),
    OwnershipRule("ext:.py", "core_engineering", "backend_developer", "software_engineering"),
    OwnershipRule("ext:.sql", "core_engineering", "backend_developer", "data_engineering"),
)

#: Especialidade líder da estratégia (`ProfessionalStrategy.lead_specialty`) → papel executor.
STRATEGY_ROLE: dict[str, str] = {
    "debugging_root_cause": "backend_developer",
    "testing_quality_assurance": "test_engineer",
    "technical_writing": "knowledge_steward",
    "refactoring_clean_code": "backend_developer",
    "system_architecture": "software_architect",
    "consultor_tecnico": "solutions_architect",
}

#: Palavras do objetivo que apontam um papel quando nenhum arquivo foi informado.
_KEYWORDS: tuple[tuple[str, str, str], ...] = (
    (r"\b(teste|testes|test|tests|cobertura|regress)", "test_engineer", "testing_quality_assurance"),
    (r"\b(document|readme|manual|guia|adr)", "knowledge_steward", "technical_writing"),
    (r"\b(interface|tela|css|bot[aã]o|layout|frontend|p[aá]gina|html|vue)", "frontend_developer", "frontend"),
    (r"\b(seguran|permiss|segredo|credencial|vulnerab)", "security_engineer", "security"),
    (r"\b(banco|sql|migra|tabela|coluna|sqlite)", "backend_developer", "data_engineering"),
    (r"\b(prompt|modelo|provedor|llm|ollama|infer)", "ai_engineer", "llm_integration"),
    (r"\b(bug|erro|falha|corrig|quebr|exce[cç])", "backend_developer", "debugging_root_cause"),
    (r"\b(arquitetur|contrato|camada|fronteira)", "software_architect", "system_architecture"),
)

#: Confiança abaixo da qual a atribuição pede investigação antes de executar.
MIN_CONFIDENCE = 0.5


def validate_catalog() -> list[str]:
    """Confere a coerência do catálogo.

    Returns:
        Os problemas encontrados (lista vazia quando o catálogo é coerente): padrão repetido,
        equipe, papel ou especialidade inexistente, revisor igual ao executor.
    """
    problems: list[str] = []
    seen: set[str] = set()
    for rule in OWNERSHIP:
        if rule.pattern in seen:
            problems.append(f"padrão com dois donos: {rule.pattern}")
        seen.add(rule.pattern)
        if rule.team not in TEAMS:
            problems.append(f"{rule.pattern}: equipe inexistente {rule.team}")
        if rule.role not in ROLES:
            problems.append(f"{rule.pattern}: papel inexistente {rule.role}")
        if rule.specialty not in SPECIALTIES:
            problems.append(f"{rule.pattern}: especialidade inexistente {rule.specialty}")
        if rule.coordination and rule.coordination not in ROLES:
            problems.append(f"{rule.pattern}: coordenação inexistente {rule.coordination}")
        if (rule.protected or rule.shared_contract) and not rule.coordination:
            problems.append(f"{rule.pattern}: área protegida sem regra de coordenação")
    for role in ROLES.values():
        if role.team not in TEAMS:
            problems.append(f"{role.id}: equipe inexistente {role.team}")
        for spec in role.specialties:
            if spec not in SPECIALTIES:
                problems.append(f"{role.id}: especialidade inexistente {spec}")
        cited = [*role.reviews, *([role.escalates_to] if role.escalates_to else [])]
        for other in cited:
            if other not in ROLES:
                problems.append(f"{role.id}: papel citado inexistente {other}")
        if role.id in role.reviews:
            problems.append(f"{role.id}: revisa o próprio trabalho")
    for executor, reviewer in DEFAULT_REVIEWER.items():
        if executor == reviewer or executor not in ROLES or reviewer not in ROLES:
            problems.append(f"revisor padrão inválido: {executor} → {reviewer}")
    return problems


# ---------------------------------------------------------------- propriedade


def _normalize(path: str) -> str:
    """Caminho relativo com barras normais, sem `./` nem barra inicial."""
    clean = str(path or "").strip().replace("\\", "/")
    while clean.startswith("./"):
        clean = clean[2:]
    return clean.lstrip("/")


def _specificity(rule: OwnershipRule, path: str) -> int:
    """Quão bem a regra casa com o caminho (0 = não casa). Prefixo vence nome de pasta, que vence extensão."""
    pattern = rule.pattern
    if pattern.startswith("ext:"):
        return 1 if path.lower().endswith(pattern[4:]) else 0
    if pattern.startswith("seg:"):
        parts = path.split("/")[:-1]
        return 5 if pattern[4:] in parts else 0
    if pattern.endswith("/"):
        return 10 + len(pattern) if path.startswith(pattern) else 0
    return 1000 + len(pattern) if path == pattern else 0


def owner_of(path: str) -> OwnershipRule | None:
    """Regra de propriedade mais específica de um caminho.

    Args:
        path: caminho relativo à raiz do projeto.

    Returns:
        A regra vencedora, ou `None` quando nenhuma casa (arquivo sem dono conhecido).
    """
    clean = _normalize(path)
    if not clean:
        return None
    best: OwnershipRule | None = None
    best_score = 0
    for rule in OWNERSHIP:
        score = _specificity(rule, clean)
        if score > best_score:
            best, best_score = rule, score
    return best


def reviewer_allowed(executor_role: str, reviewer_role: str) -> bool:
    """Diz se `reviewer_role` pode aprovar o trabalho de `executor_role`.

    A regra é a independência: ninguém aprova o próprio trabalho. Além disso, o revisor precisa
    ter o executor entre os papéis que revisa ou ser o revisor padrão dele; o Product Owner
    (humano) pode aprovar qualquer papel.
    """
    if not reviewer_role or reviewer_role == executor_role or reviewer_role not in ROLES:
        return False
    if reviewer_role == "product_owner":
        return True
    if DEFAULT_REVIEWER.get(executor_role) == reviewer_role:
        return True
    return executor_role in ROLES[reviewer_role].reviews


# ----------------------------------------------------------------- seleção


@dataclass
class Assignment:
    """Resultado da seleção de responsável, com a justificativa rastreável."""

    team: str
    role: str
    reviewer_role: str
    specialties: list[str]
    skills: list[str]
    domain: str
    complexity: str
    risk: str
    confidence: float
    rationale: list[str] = field(default_factory=list)
    affected_modules: list[str] = field(default_factory=list)
    protected_files: list[str] = field(default_factory=list)
    shared_contracts: list[str] = field(default_factory=list)
    coordination: list[str] = field(default_factory=list)
    needs_investigation: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Forma serializável (JSON) da atribuição."""
        return {
            "team": self.team,
            "role": self.role,
            "reviewer_role": self.reviewer_role,
            "specialties": list(self.specialties),
            "skills": list(self.skills),
            "domain": self.domain,
            "complexity": self.complexity,
            "risk": self.risk,
            "confidence": round(self.confidence, 2),
            "rationale": list(self.rationale),
            "affected_modules": list(self.affected_modules),
            "protected_files": list(self.protected_files),
            "shared_contracts": list(self.shared_contracts),
            "coordination": list(self.coordination),
            "needs_investigation": self.needs_investigation,
        }


def _module_of(rule: OwnershipRule, path: str) -> str:
    """Nome do módulo afetado: o prefixo da regra, ou a pasta do arquivo nas regras genéricas."""
    if rule.pattern.startswith(("ext:", "seg:")):
        folder = path.rsplit("/", 1)[0] if "/" in path else "."
        return folder + "/" if folder != "." else "."
    return rule.pattern


def select_assignment(
    *,
    objective: str,
    paths: list[str] | None = None,
    kind: str = "operation",
    lead_specialty: str | None = None,
) -> Assignment:
    """Escolhe equipe, papel, revisor e especialidades de uma tarefa.

    A ordem de evidência é: arquivos do escopo (propriedade), especialidade líder da estratégia,
    palavras do objetivo. Tarefa de objetivo (raiz) fica com o tech lead, que coordena. Quando
    nada aponta um responsável com confiança, a atribuição pede investigação em vez de escolher
    ao acaso.

    Args:
        objective: objetivo da tarefa.
        paths: arquivos do escopo (`allowed_files`), relativos à raiz.
        kind: tipo da tarefa (`objective`, `subsystem` ou `operation`).
        lead_specialty: especialidade líder da estratégia profissional, quando houver.

    Returns:
        A atribuição com justificativa, risco, complexidade e coordenação exigida.
    """
    rationale: list[str] = []
    votes: dict[tuple[str, str], int] = {}
    specialty_votes: dict[str, int] = {}
    modules: dict[str, None] = {}
    protected: list[str] = []
    shared: list[str] = []
    coordination: dict[str, None] = {}
    known = 0
    clean_paths = [p for p in (_normalize(x) for x in (paths or [])) if p]
    for path in clean_paths:
        rule = owner_of(path)
        if rule is None:
            continue
        known += 1
        votes[(rule.team, rule.role)] = votes.get((rule.team, rule.role), 0) + 1
        specialty_votes[rule.specialty] = specialty_votes.get(rule.specialty, 0) + 1
        modules.setdefault(_module_of(rule, path), None)
        if rule.protected:
            protected.append(path)
        if rule.shared_contract:
            shared.append(path)
        if rule.coordination and (rule.protected or rule.shared_contract):
            coordination.setdefault(rule.coordination, None)

    team = role = ""
    specialty = ""
    confidence = 0.0
    if votes:
        (team, role), top = max(votes.items(), key=lambda item: item[1])
        specialty = max(specialty_votes.items(), key=lambda item: item[1])[0]
        confidence = top / max(len(clean_paths), 1)
        rationale.append(
            f"{top} de {len(clean_paths)} arquivo(s) do escopo pertencem a {TEAMS[team].name}"
        )
        if len(votes) > 1:
            rationale.append(f"o escopo cruza {len(votes)} áreas; as demais entram como coordenação")
    if lead_specialty and lead_specialty in STRATEGY_ROLE:
        strategy_role = STRATEGY_ROLE[lead_specialty]
        if not role or confidence < MIN_CONFIDENCE:
            role = strategy_role
            team = ROLES[role].team
            specialty = lead_specialty if lead_specialty in SPECIALTIES else ROLES[role].specialties[0]
            confidence = max(confidence, 0.7)
            rationale.append(f"especialidade líder da estratégia: {lead_specialty}")
        elif lead_specialty in SPECIALTIES and lead_specialty != specialty:
            specialty_votes.setdefault(lead_specialty, 0)
            rationale.append(f"especialidade da estratégia somada: {lead_specialty}")
    if not role:
        text = (objective or "").lower()
        for pattern, kw_role, kw_spec in _KEYWORDS:
            if re.search(pattern, text):
                role, specialty = kw_role, kw_spec
                team = ROLES[role].team
                confidence = 0.6
                rationale.append(f"o objetivo fala de {kw_spec.replace('_', ' ')}")
                break
    if not role:
        role, team, specialty = "backend_developer", "core_engineering", "software_engineering"
        confidence = 0.3
        rationale.append("nenhum arquivo nem palavra do objetivo aponta a área; responsável provisório")

    if kind == "objective":
        rationale.append(f"tarefa raiz: o tech lead coordena; a execução fica com {ROLES[role].name}")
        role, team = "tech_lead", "core_engineering"
    reviewer = DEFAULT_REVIEWER.get(role, "qa_engineer")
    if protected and reviewer != "software_architect" and role != "software_architect":
        coordination.setdefault("software_architect", None)
    if any(owner_of(p) and owner_of(p).specialty == "security" for p in clean_paths):
        coordination.setdefault("security_engineer", None)
    coordination.pop(role, None)

    teams_touched = {t for (t, _r) in votes}
    if protected:
        risk = "high"
        rationale.append(f"toca área protegida: {', '.join(protected[:3])}")
    elif shared or len(teams_touched) > 1:
        risk = "medium"
        if shared:
            rationale.append(f"toca contrato compartilhado: {', '.join(shared[:3])}")
    else:
        risk = "low"
    if kind == "objective" or len(clean_paths) > 4 or len(teams_touched) > 2:
        complexity = "high"
    elif len(clean_paths) > 1 or len(teams_touched) > 1 or kind == "subsystem":
        complexity = "medium"
    else:
        complexity = "low"

    specialties = [specialty] + [s for s in specialty_votes if s != specialty]
    skills = list(dict.fromkeys(SPECIALTIES[s].skill_id for s in specialties if s in SPECIALTIES))
    needs_investigation = confidence < MIN_CONFIDENCE
    if needs_investigation:
        rationale.append("confiança baixa: investigar o escopo antes de executar")
    if known < len(clean_paths):
        rationale.append(f"{len(clean_paths) - known} arquivo(s) sem dono conhecido")
    return Assignment(
        team=team,
        role=role,
        reviewer_role=reviewer,
        specialties=specialties,
        skills=skills,
        domain=specialty,
        complexity=complexity,
        risk=risk,
        confidence=confidence,
        rationale=rationale,
        affected_modules=list(modules),
        protected_files=protected,
        shared_contracts=shared,
        coordination=list(coordination),
        needs_investigation=needs_investigation,
    )
