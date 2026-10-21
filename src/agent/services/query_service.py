"""
Arquivo: src/agent/services/query_service.py
Nome: query_service.py
Propósito: implementar o protocolo de consulta entre agentes, em qualquer geração.
Responsabilidade: camada de aplicação — criação, resolução e correlação das consultas.
Componentes: QueryService, QueryRejectedError.
Dependências: agent.domain.agent_enums, agent.persistence.models, agent.services.agent_service, agent.providers.base.
Observações: a resposta persistida é devolvida sem inferência; só a falta de informação ativa o filho.

Protocolo de consulta entre agentes, em qualquer geração.

O problema que este módulo resolve: quando o filho termina, o pai precisa de uma
*resposta*, não do *histórico* do filho. Relatórios extensos a cada delegação estouram
o contexto do pai e o trabalho é refeito a cada pergunta.

O protocolo é o mesmo em toda a hierarquia:

1. o pai delega a tarefa;
2. o filho executa e persiste as descobertas;
3. o filho devolve um resultado inicial conciso;
4. o filho pode ser suspenso — continua consultável;
5. quando surge a dúvida, o pai pergunta **por identificador de tarefa/agente**;
6. o sistema recupera o estado persistido;
7. se o estado já contém a resposta, ela é devolvida **sem inferência**;
8. só quando falta informação o filho é reativado, e a inferência passa pelo
   executor compartilhado;
9. a resposta e as novas descobertas são persistidas;
10. o contexto temporário é liberado e o pai continua.

Estratégia de roteamento: **direcionada**. A consulta vai ao agente perguntado; se ele
não tem a informação, a busca desce pela descendência até alguém que tenha — cada
nível responde pelo seu próprio estado, sem que o neto precise enviar o histórico
para o filho, do filho para o pai e do pai para o avô.
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent.config import Settings, get_settings
from agent.domain.agent_enums import ExecutionStatus, QueryStatus
from agent.persistence.models import AgentModel, AgentQueryModel
from agent.services.agent_service import AgentNotFoundError, AgentService
from agent.providers.base import (
    ChatCompletionRequest,
    ChatMessage,
    LLMProvider,
    ModelProfile,
)

__all__ = ["QueryService", "QueryRejectedError", "QUESTION_STOPWORDS"]

#: Palavras vazias em português: não carregam tema e não devem contar como evidência.
QUESTION_STOPWORDS = frozenset(
    {
        "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "da", "do", "das", "dos",
        "e", "ou", "que", "qual", "quais", "quem", "como", "quando", "onde", "por", "para",
        "com", "sem", "no", "na", "nos", "nas", "em", "foi", "foi", "era", "e", "se",
        "isso", "isto", "este", "esta", "esse", "essa", "aquele", "aquela", "o", "ao",
        "aos", "da", "pelo", "pela", "sobre", "entre", "ainda", "mais", "menos", "seu",
        "sua", "meu", "minha", "nos", "ele", "ela", "eles", "elas", "está", "esta",
        "foram", "tem", "têm", "fazer", "feito", "passou", "ficou", "deve", "deveria",
        "existe", "há", "so", "só",
    }
)

_WORD_RE = re.compile(r"[a-z0-9_]+")

#: Formas de dizer "não há evidência". Modelos pequenos tokenizam mal o sentinela
#: (`SEM_EVIDENCIA` vira "SEMA INFORMAÇÃO FALTA" num 3B), então o reconhecimento
#: é por intenção, não por palavra exata.
_ABSENCE_PATTERN = re.compile(
    r"sem\s*_?evid[eê]ncia"
    r"|sem\s+informa"
    r"|sema\s+informa"
    r"|n[aã]o\s+h[aá]\s+(informa|evid[eê]ncia|resposta|dado|registro)"
    r"|n[aã]o\s+consta"
    r"|n[aã]o\s+(foi\s+)?poss[ií]vel"
    r"|n[aã]o\s+possu[ií]"
    r"|n[aã]o\s+encontrei",
    re.IGNORECASE,
)


def _declara_ausencia(texto: str) -> bool:
    """O texto diz que não há evidência disponível?

    Args:
        texto: resposta do agente.

    Returns:
        `True` quando a resposta declara ausência de informação.
    """
    return bool(_ABSENCE_PATTERN.search(texto or ""))


def _sem_acento(text: str) -> str:
    """Remove diacríticos.

    Sem isso, "cálculo" vira "c" + "lculo" e nunca casa com "cálculo": em português,
    quase toda palavra técnica tem acento. É um defeito silencioso — a consulta apenas
    não encontra a evidência que existe.

    Args:
        text: texto de entrada.

    Returns:
        O texto sem diacríticos.
    """
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _tokens(text: str) -> set[str]:
    """Palavras úteis do texto, sem acentos, sem palavras vazias e sem as curtas demais.

    Args:
        text: texto de entrada.

    Returns:
        O conjunto de tokens significativos.
    """
    words = _WORD_RE.findall(_sem_acento(text).lower())
    return {w for w in words if len(w) > 2 and w not in QUESTION_STOPWORDS}


def _normalize(text: str) -> str:
    """Normaliza o texto para comparação lexical.

    Args:
        text: texto de entrada.

    Returns:
        O texto sem acentos, em minúsculas e apenas com palavras.
    """
    return " ".join(_WORD_RE.findall(_sem_acento(text).lower()))


class QueryRejectedError(ValueError):
    """Consulta recusada: violaria uma regra do protocolo (ciclo, limite, alvo)."""


class QueryService:
    """Consultas entre agentes: criação, resolução e correlação de respostas.

    Atributos:
        _session: sessão usada nas leituras e gravações.
        _settings: configurações, com os limites do protocolo.
        _agents: serviço dos agentes, usado para validar e rotear a consulta.
    """

    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        *,
        agent_service: AgentService | None = None,
    ) -> None:
        """Cria o serviço ligado a uma sessão.

        Args:
            session: sessão SQLAlchemy a usar.
            settings: configurações a usar; quando ausentes, são lidas do ambiente.
            agent_service: serviço dos agentes; quando ausente, é criado com a mesma sessão.
        """
        self._session = session
        self._settings = settings or get_settings()
        self._agents = agent_service or AgentService(session, self._settings)

    # -------------------------------------------------------------- criação

    def ask(
        self,
        requester_agent_id: uuid.UUID,
        target_agent_id: uuid.UUID,
        question: str | list[str],
        *,
        task_id: uuid.UUID | None = None,
        correlation_id: str | None = None,
        max_attempts: int | None = None,
    ) -> AgentQueryModel:
        """Registra a pergunta do solicitante ao alvo.

        Regras aplicadas na criação (falhar cedo é melhor do que consultar em ciclo):

        - o alvo existe e não é ancestral do solicitante (consulta circular);
        - o solicitante não tem mais consultas pendentes que o limite permita;
        - perguntas relacionadas podem ser agrupadas em uma só consulta.

        Args:
            requester_agent_id: agente que pergunta.
            target_agent_id: agente perguntado.
            question: a pergunta, ou a lista de perguntas agrupadas.
            task_id: tarefa associada à consulta.
            correlation_id: identificador de correlação; por padrão, é gerado.
            max_attempts: limite de tentativas da consulta.

        Returns:
            A consulta registrada, pendente.

        Raises:
            QueryRejectedError: quando a consulta viola uma regra do protocolo.
        """
        requester = self._agents.get(requester_agent_id)
        target = self._agents.get(target_agent_id)
        questions = [question] if isinstance(question, str) else list(question)
        questions = [q.strip() for q in questions if q and q.strip()]
        if not questions:
            raise QueryRejectedError("a consulta precisa de pelo menos uma pergunta")
        if requester.id == target.id:
            raise QueryRejectedError("um agente não consulta a si mesmo")
        ancestor_ids = {a.id for a in self._agents.ancestors(requester.id)}
        if target.id in ancestor_ids:
            raise QueryRejectedError(
                "consulta circular: o alvo é ancestral do solicitante"
            )
        pending = self.pending_for(target.id)
        if len(pending) >= self._settings.max_pending_queries_per_agent:
            raise QueryRejectedError(
                f"o agente alvo já tem {len(pending)} consultas pendentes "
                f"(limite {self._settings.max_pending_queries_per_agent})"
            )
        correlation = correlation_id or uuid.uuid4().hex[:16]
        query = AgentQueryModel(
            project_id=requester.project_id,
            requester_agent_id=requester.id,
            target_agent_id=target.id,
            task_id=task_id or target.task_id,
            correlation_id=correlation,
            questions_json=questions,
            status=QueryStatus.PENDING.value,
            attempts=0,
            max_attempts=max_attempts or self._settings.max_query_attempts,
        )
        self._session.add(query)
        self._session.flush()
        return query

    # -------------------------------------------------------------- leitura

    def get(self, query_id: uuid.UUID) -> AgentQueryModel:
        """Consulta por identificador.

        Args:
            query_id: identificador da consulta.

        Returns:
            A consulta encontrada.

        Raises:
            AgentNotFoundError: quando a consulta não existe.
        """
        query = self._session.get(AgentQueryModel, query_id)
        if query is None:
            raise AgentNotFoundError(f"Consulta não encontrada: {query_id}")
        return query

    def pending_for(self, agent_id: uuid.UUID) -> list[AgentQueryModel]:
        """Consultas pendentes dirigidas a um agente.

        Args:
            agent_id: identificador do agente alvo.

        Returns:
            A lista de consultas pendentes ou roteadas, da mais antiga para a mais recente.
        """
        stmt = (
            select(AgentQueryModel)
            .where(
                AgentQueryModel.target_agent_id == agent_id,
                AgentQueryModel.status.in_(
                    [QueryStatus.PENDING.value, QueryStatus.ROUTED.value]
                ),
            )
            .order_by(AgentQueryModel.created_at, AgentQueryModel.id)
        )
        return list(self._session.scalars(stmt).all())

    def queries_of(self, agent_id: uuid.UUID) -> list[AgentQueryModel]:
        """Consultas em que um agente participa, como solicitante ou alvo.

        Args:
            agent_id: identificador do agente.

        Returns:
            A lista de consultas, da mais antiga para a mais recente.
        """
        stmt = (
            select(AgentQueryModel)
            .where(
                (AgentQueryModel.requester_agent_id == agent_id)
                | (AgentQueryModel.target_agent_id == agent_id)
            )
            .order_by(AgentQueryModel.created_at, AgentQueryModel.id)
        )
        return list(self._session.scalars(stmt).all())

    # ------------------------------------------------------------ resolução

    def _relevant(self, question: str, findings: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Descoberta persistida que responde à pergunta (busca lexical, sem inferência).

        Dois critérios, do mais forte ao mais fraco:

        - **forte**: ao menos duas palavras em comum e a maior parte da pergunta
          coberta — é o caso direto ("causa da falha" ↔ "A causa da falha foi…");
        - **fraco**: uma palavra comum, **distintiva** (6+ letras) que cobre **ao menos
          metade** da pergunta — o caso indireto curto ("onde foi o deploy?" ↔ "O
          deploy foi…").

        O fraco é aceito porque a medição showed perguntas diretas legítimas sendo
        descartadas. O limite de cobertura é o que segura o risco: a medição mostrou
        que "qual framework de testes foi adotado?" casaria com "Os testes executados
        foram…" se a palavra "testes" bastasse — e isso é inventar resposta. Com o
        limite, a pergunta cai no caminho de inferência, que é o lugar honesto para
        uma pergunta ambígua.

        Args:
            question: pergunta feita ao agente.
            findings: descobertas persistidas do agente.

        Returns:
            A descoberta pertinente, com o campo `_match_strength`, ou `None`.
        """
        q_tokens = _tokens(question)
        if not q_tokens:
            return None
        best: tuple[float, int, dict[str, Any]] | None = None
        for finding in findings:
            text = _normalize(finding.get("text", ""))
            shared = q_tokens & set(text.split())
            if not shared:
                continue
            score = len(shared) / len(q_tokens)
            distintivas = [t for t in shared if len(t) >= 6]
            forte = score >= 0.34 and len(shared) >= 2
            fraco = bool(distintivas) and score >= 0.5
            if not (forte or fraco):
                continue
            # Desempate: forte vence fraco; dentro da mesma força, a maior cobertura.
            forca = 2 if forte else 1
            if best is None or (forca, score) > (best[1], best[0]):
                best = (score, forca, finding)
        if best is None:
            return None
        matched = dict(best[2])
        matched["_match_strength"] = "direct" if best[1] == 2 else "weak"
        return matched

    def answer_from_persisted(self, query: AgentQueryModel) -> dict[str, Any] | None:
        """Responde a partir do estado já persistido, sem reativar ninguém.

        A busca é direcionada: primeiro o alvo, depois a descendência, em ordem de
        profundidade. O primeiro agente com evidência pertinente responde.

        Args:
            query: consulta a responder.

        Returns:
            A resposta montada a partir do estado persistido, ou `None` quando nada responde.
        """
        questions = list(query.questions_json or [])
        combined = " ".join(questions)
        for agent in [self._agents.get(query.target_agent_id), *self._agents.descendants(query.target_agent_id)]:
            finding = self._relevant(combined, self._agents.findings(agent.id))
            if finding is None:
                continue
            return {
                "answer": finding.get("text", ""),
                "evidence": list(finding.get("evidence") or []),
                "artifacts": list(finding.get("artifacts") or []),
                "uncertainty": [],
                "source_agent_id": str(agent.id),
                "source_task_id": str(agent.task_id) if agent.task_id else None,
                "from_persisted_state": True,
                "inference_used": False,
                "match_strength": finding.get("_match_strength", "direct"),
            }
        return None

    def _context_for(self, agent: AgentModel, *, limit: int = 4000) -> str:
        """Contexto mínimo do próprio agente: checkpoint e descoberta, sem transcrição.

        O contexto é limitado de propósito: o pai não precisa do histórico do filho,
        só do que sustenta a resposta. O que ficou de fora continua no estado
        persistido e pode ser consultado em outra rodada.

        Args:
            agent: agente consultado.
            limit: tamanho máximo do contexto, em caracteres.

        Returns:
            O contexto do agente, em texto.
        """
        return self._context_for_agents([agent], limit=limit)

    def _context_for_agents(
        self, agents: list[AgentModel], *, limit: int = 4000
    ) -> str:
        """Contexto de um conjunto de agentes, com atribuição de quem descobriu o quê.

        A atribuição importa: o pai precisa saber de quem veio a evidência, e a
        verificação de lastro compara a resposta com exatamente este contexto.

        Args:
            agents: agentes cujo estado é resumido.
            limit: tamanho máximo do contexto, em caracteres.

        Returns:
            O contexto em texto, com um bloco por agente.
        """
        blocks: list[str] = []
        for candidate in agents:
            findings = self._agents.findings(candidate.id)
            checkpoint = self._agents.checkpoint(candidate.id)
            if not findings and not checkpoint:
                continue
            lines: list[str] = []
            if checkpoint:
                lines.append("ETAPA DO TRABALHO:")
                for key in ("objective", "step", "plan_index", "pending", "errors"):
                    if checkpoint.get(key):
                        lines.append(f"- {key}: {checkpoint[key]}")
            if findings:
                lines.append("DESCOBERTAS:")
                for finding in findings[-8:]:
                    evidence = ", ".join(finding.get("evidence") or [])
                    suffix = f" (evidência: {evidence})" if evidence else ""
                    lines.append(f"- {finding.get('text', '')}{suffix}")
            blocks.append(
                f"AGENTE {candidate.role} ({candidate.id}):\n" + "\n".join(lines)
            )
        if not blocks:
            return "(sem estado persistido)"
        text = "\n\n".join(blocks)
        if len(text) > limit:
            text = text[:limit] + "\n(contexto truncado; o restante está no estado persistido)"
        return text

    def _subtree_context(self, agent: AgentModel, *, limit: int = 4000) -> str:
        """Estado do agente e de sua descendência.

        A busca lexical desce pela hierarquia; o caminho de inferência precisa ver o
        mesmo material — senão o modelo responde sem a evidência que existe no neto.

        Args:
            agent: agente raiz da subárvore.
            limit: tamanho máximo do contexto, em caracteres.

        Returns:
            O contexto do agente e de sua descendência, em texto.
        """
        return self._context_for_agents(
            [agent, *self._agents.descendants(agent.id)], limit=limit
        )

    async def resolve(
        self,
        query_id: uuid.UUID,
        *,
        provider: LLMProvider | None = None,
        profile: ModelProfile | None = None,
    ) -> AgentQueryModel:
        """Resolve a consulta: estado persistido primeiro, inferência só se faltar.

        A resposta é sempre persistida e correlacionada à consulta — uma resposta nunca
        fica associated a outra tarefa.

        Args:
            query_id: identificador da consulta.
            provider: provedor usado quando for preciso inferir.
            profile: perfil do modelo usado na inferência.

        Returns:
            A consulta resolvida, com o estado e a resposta.

        Raises:
            AgentNotFoundError: quando a consulta não existe.
        """
        query = self.get(query_id)
        if query.status == QueryStatus.ANSWERED.value:
            return query
        if query.attempts >= query.max_attempts:
            query.status = QueryStatus.FAILED.value
            query.error_message = "limite de tentativas atingido"
            self._session.flush()
            return query
        query.attempts = (query.attempts or 0) + 1
        query.status = QueryStatus.ROUTED.value
        self._session.flush()

        try:
            answer = self.answer_from_persisted(query)
            if answer is None and provider is not None and profile is not None:
                answer = await self._answer_with_inference(query, provider, profile)
        except Exception as exc:
            # A tentativa contada não pode ser desfeita. A consulta volta a PENDING (e não
            # ROUTED, que o worker não recolhe) com o contador intacto: quem chamou precisa
            # **confirmar** a transação, senão o rollback devolve a consulta ao estado
            # anterior e ela é reenviada para sempre, gastando inferência a cada tique.
            query.error_message = f"{type(exc).__name__}: {exc}"[:500]
            query.status = QueryStatus.PENDING.value
            self._session.flush()
            raise
        if answer is None:
            answer = {
                "answer": "Sem evidência no estado persistido do agente consultado.",
                "evidence": [],
                "artifacts": [],
                "uncertainty": [
                    "O estado persistido do agente e de seus descendentes não contém "
                    "a informação solicitada."
                ],
                "source_agent_id": str(query.target_agent_id),
                "source_task_id": str(query.task_id) if query.task_id else None,
                "from_persisted_state": True,
                "inference_used": False,
            }
        query.answer = str(answer.get("answer", ""))
        query.answer_json = answer
        query.status = QueryStatus.ANSWERED.value
        query.answered_at = datetime.now(timezone.utc)
        query.answered_by_agent_id = uuid.UUID(answer["source_agent_id"]) if answer.get("source_agent_id") else None
        self._session.flush()
        return query

    def _is_grounded(self, answer: str, agent: AgentModel) -> tuple[bool, list[str]]:
        """A resposta da inferência encontra respaldo no estado persistido?

        Verificação lexical barata, mas que não depende da boa vontade do modelo: uma
        resposta que não compartilha nenhum conteúdo com o estado do agente é marcada
        como **não fundamentada**. A resposta não é descartada — ela é marcada, porque
        o pai precisa saber se pode confiar.

        Args:
            answer: resposta produzida pela inferência.
            agent: agente consultado.

        Returns:
            Tupla com o indicativo de fundamentação e a lista de incertezas.
        """
        answer_tokens = _tokens(answer)
        if not answer_tokens:
            return False, ["a resposta do modelo veio vazia"]
        state_tokens = _tokens(self._subtree_context(agent))
        shared = answer_tokens & state_tokens
        if not shared:
            return False, [
                "a resposta do modelo não encontra respaldo no estado persistido do agente"
            ]
        return True, []

    async def _answer_with_inference(
        self,
        query: AgentQueryModel,
        provider: LLMProvider,
        profile: ModelProfile,
    ) -> dict[str, Any]:
        """Reativa o agente consultado e responde com uma inferência pelo executor compartilhado.

        Args:
            query: consulta a responder.
            provider: provedor chamado.
            profile: perfil do modelo.

        Returns:
            A resposta da inferência, ou `None` quando o modelo devolveu texto vazio.
        """
        agent = self._agents.get(query.target_agent_id)
        execution = self._agents.current_execution(agent.id)
        if execution is not None and execution.status == ExecutionStatus.SUSPENDED.value:
            self._agents.resume(agent.id)
        questions = list(query.questions_json or [])
        prompt = (
            f"Você é o agente '{agent.role}' do projeto. Responda às perguntas do agente "
            "solicitante usando APENAS o estado persistido abaixo. Se a informação não "
            "estiver no estado, responda exatamente SEM_EVIDENCIA e diga o que falta. "
            "Seja conciso: no máximo 10 linhas, citing arquivos quando houver.\n\n"
            f"ESTADO PERSISTIDO DO AGENTE E DE SEUS DESCENDENTES:\n"
            f"{self._subtree_context(agent)}\n\n"
            "PERGUNTAS:\n"
            + "\n".join(f"- {q}" for q in questions)
        )
        request = ChatCompletionRequest(
            messages=[ChatMessage(role="user", content=prompt)],
            profile=profile,
        )
        from agent.observability.emitter import current, observe
        from agent.orchestrator.budget_gate import use_budget_settings
        from agent.providers.observed import observed_chat

        async def _ask():
            """Passa a consulta pelo mesmo controlador das outras inferências."""
            return await observed_chat(provider, request, purpose="agent_query", stream=False)

        if current() is None and execution is not None and execution.run_id:
            with use_budget_settings(self._settings):
                with observe(
                    self._session,
                    run_id=execution.run_id,
                    project_id=agent.project_id,
                    task_id=agent.task_id,
                    agent=agent.role,
                ):
                    response = await _ask()
        else:
            response = await _ask()
        content = (response.content or "").strip()
        if not content:
            return None
        if _declara_ausencia(content):
            return {
                "answer": "Sem evidência no estado persistido do agente consultado.",
                "evidence": [],
                "artifacts": [],
                "uncertainty": [content[:1000]],
                "source_agent_id": str(agent.id),
                "source_task_id": str(agent.task_id) if agent.task_id else None,
                "from_persisted_state": True,
                "inference_used": True,
                "grounded": False,
            }
        fundamentada, incertezas = self._is_grounded(content, agent)
        if not fundamentada:
            # O modelo respondeu algo que não está no estado. A resposta é preservada,
            # mas marcada: o pai precisa saber que ela não tem lastro.
            content = "[sem evidência no estado persistido] " + content
        # A resposta da inferência vira descoberta do agente: a pergunta equivalente
        # passa a ser respondida pelo estado persistido, sem nova inferência.
        self._remember_inference(agent, content, fundamentada)
        return {
            "answer": content,
            "evidence": [],
            "artifacts": [],
            "uncertainty": incertezas,
            "source_agent_id": str(agent.id),
            "source_task_id": str(agent.task_id) if agent.task_id else None,
            "from_persisted_state": False,
            "inference_used": True,
            "grounded": fundamentada,
        }

    def _remember_inference(self, agent: AgentModel, content: str, fundamentada: bool) -> None:
        """Guarda a resposta sintetizada como descoberta do agente consultado.

        Args:
            agent: agente consultado.
            content: resposta sintetizada.
            fundamentada: indica se a resposta encontra respaldo no estado persistido.
        """
        try:
            self._agents.record_finding(
                agent.id,
                content,
                kind="inference",
                evidence=[] if fundamentada else ["[sem evidência no estado persistido]"],
            )
        except Exception:  # pragma: no cover - a descoberta é cache, não requisito
            return

    # ------------------------------------------------------------- respostas

    def answer(
        self,
        query_id: uuid.UUID,
        answer: str,
        *,
        evidence: list[str] | None = None,
        artifacts: list[str] | None = None,
        uncertainty: list[str] | None = None,
        answered_by_agent_id: uuid.UUID | None = None,
    ) -> AgentQueryModel:
        """Registra a resposta de um agente a uma consulta (caminho sem inferência).

        Args:
            query_id: identificador da consulta.
            answer: texto da resposta.
            evidence: provas que sustentam a resposta.
            artifacts: arquivos envolvidos.
            uncertainty: pontos de incerteza da resposta.
            answered_by_agent_id: agente que respondeu.

        Returns:
            A consulta respondida.

        Raises:
            AgentNotFoundError: quando a consulta não existe.
        """
        query = self.get(query_id)
        payload = {
            "answer": answer,
            "evidence": list(evidence or []),
            "artifacts": list(artifacts or []),
            "uncertainty": list(uncertainty or []),
            "source_agent_id": str(answered_by_agent_id or query.target_agent_id),
            "source_task_id": str(query.task_id) if query.task_id else None,
            "from_persisted_state": True,
            "inference_used": False,
        }
        query.answer = answer
        query.answer_json = payload
        query.status = QueryStatus.ANSWERED.value
        query.answered_at = datetime.now(timezone.utc)
        if answered_by_agent_id is not None:
            query.answered_by_agent_id = answered_by_agent_id
        self._session.flush()
        return query

    def cancel(self, query_id: uuid.UUID, *, reason: str = "") -> AgentQueryModel:
        """Cancela uma consulta pendente.

        Args:
            query_id: identificador da consulta.
            reason: motivo do cancelamento.

        Returns:
            A consulta cancelada.

        Raises:
            AgentNotFoundError: quando a consulta não existe.
        """
        query = self.get(query_id)
        query.status = QueryStatus.CANCELLED.value
        query.error_message = reason[:500]
        self._session.flush()
        return query
