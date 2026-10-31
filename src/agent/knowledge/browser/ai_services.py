"""
Arquivo: src/agent/knowledge/browser/ai_services.py
Nome: ai_services.py
Propósito: integração com serviços de IA via navegador autenticado (ChatGPT, Gemini, Claude).
Responsabilidade: camada de infraestrutura — envia perguntas e captura respostas de IAs externas.
Componentes: AIServiceBase, ChatGPTService, GeminiService, ClaudeService, AIServiceManager.
Dependências: src.agent.knowledge.browser.session, asyncio.
Observações: requer autenticação manual prévia do usuário nos serviços; não automatiza login.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from agent.knowledge.browser.session import AuthenticatedBrowserSession


@dataclass
class AIResponse:
    """Resposta normalizada de um serviço de IA."""

    service: str
    question: str
    answer: str
    model: str | None = None
    conversation_id: str | None = None
    timestamp: datetime = None
    raw_html: str | None = None
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(UTC)
        if self.metadata is None:
            self.metadata = {}


class AIServiceBase(ABC):
    """Classe base para serviços de IA via navegador."""

    def __init__(self, session: AuthenticatedBrowserSession) -> None:
        self.session = session
        self.service_name = self.__class__.__name__.replace("Service", "").lower()

    @property
    @abstractmethod
    def base_url(self) -> str:
        """URL base do serviço."""
        pass

    @property
    @abstractmethod
    def chat_url(self) -> str:
        """URL da interface de chat."""
        pass

    @abstractmethod
    async def send_question(self, question: str, *, wait_time: float = 30) -> AIResponse:
        """Envia pergunta e aguarda resposta."""
        pass

    @abstractmethod
    async def is_authenticated(self) -> bool:
        """Verifica se a sessão está autenticada."""
        pass

    async def _wait_for_response(self, selector: str, timeout: float = 60) -> str:
        """Aguarda resposta aparecer no elemento indicado."""
        start = asyncio.get_event_loop().time()
        last_text = ""
        stable_count = 0

        while asyncio.get_event_loop().time() - start < timeout:
            try:
                text = await self.session.get_text(selector)
                if text and text != last_text:
                    if len(text) > len(last_text):
                        last_text = text
                        stable_count = 0
                    else:
                        stable_count += 1
                        if stable_count >= 3:  # Texto estabilizou
                            break
                else:
                    stable_count += 1
                    if stable_count >= 5:
                        break
            except Exception:
                pass
            await asyncio.sleep(1)

        return last_text

    def _clean_response(self, text: str) -> str:
        """Limpa resposta removendo artefatos da UI."""
        # Remover timestamps, botões, etc.
        text = re.sub(r"\d{1,2}:\d{2}\s*(AM|PM)?", "", text)
        text = re.sub(r"Copy code|Regenerate|Share|Export", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


class ChatGPTService(AIServiceBase):
    """Serviço ChatGPT (chat.openai.com)."""

    @property
    def base_url(self) -> str:
        return "https://chat.openai.com"

    @property
    def chat_url(self) -> str:
        return "https://chat.openai.com/"

    async def is_authenticated(self) -> bool:
        try:
            await self.session.navigate(self.chat_url)
            await self.session.wait_for_selector("textarea[data-id='root']", timeout=10000)
            return True
        except Exception:
            return False

    async def send_question(self, question: str, *, wait_time: float = 45) -> AIResponse:
        if not await self.is_authenticated():
            raise RuntimeError("ChatGPT: sessão não autenticada. Faça login manualmente primeiro.")

        # Navegar para nova conversa se necessário
        await self.session.navigate("https://chat.openai.com/")
        await asyncio.sleep(2)

        # Encontrar e preencher campo de input
        try:
            await self.session.wait_for_selector("textarea[data-id='root']", timeout=10000)
            await self.session.fill("textarea[data-id='root']", question)
            await asyncio.sleep(0.5)
            await self.session.press("textarea[data-id='root']", "Enter")
        except Exception as e:
            raise RuntimeError(f"Falha ao enviar pergunta: {e}")

        # Aguardar resposta
        # ChatGPT usa streaming - aguardar estabilização
        response_text = await self._wait_for_response(
            "div[data-message-author-role='assistant']",
            timeout=wait_time
        )

        cleaned = self._clean_response(response_text)

        return AIResponse(
            service="chatgpt",
            question=question,
            answer=cleaned,
            model="gpt-4",  # Detectar dinamicamente no futuro
            raw_html=response_text,
        )


class GeminiService(AIServiceBase):
    """Serviço Google Gemini (gemini.google.com)."""

    @property
    def base_url(self) -> str:
        return "https://gemini.google.com"

    @property
    def chat_url(self) -> str:
        return "https://gemini.google.com/app"

    async def is_authenticated(self) -> bool:
        try:
            await self.session.navigate(self.chat_url)
            await self.session.wait_for_selector("textarea[aria-label*='Enter']", timeout=10000)
            return True
        except Exception:
            return False

    async def send_question(self, question: str, *, wait_time: float = 45) -> AIResponse:
        if not await self.is_authenticated():
            raise RuntimeError("Gemini: sessão não autenticada. Faça login manualmente primeiro.")

        await self.session.navigate(self.chat_url)
        await asyncio.sleep(2)

        try:
            # Campo de input do Gemini
            await self.session.wait_for_selector("textarea[aria-label*='Enter']", timeout=10000)
            await self.session.fill("textarea[aria-label*='Enter']", question)
            await asyncio.sleep(0.5)
            await self.session.press("textarea[aria-label*='Enter']", "Enter")
        except Exception as e:
            raise RuntimeError(f"Falha ao enviar pergunta: {e}")

        # Aguardar resposta - Gemini usa div com role='model'
        response_text = await self._wait_for_response(
            "div[role='model'], message-content, .model-response-text",
            timeout=wait_time
        )

        cleaned = self._clean_response(response_text)

        return AIResponse(
            service="gemini",
            question=question,
            answer=cleaned,
            model="gemini-pro",
            raw_html=response_text,
        )


class ClaudeService(AIServiceBase):
    """Serviço Anthropic Claude (claude.ai)."""

    @property
    def base_url(self) -> str:
        return "https://claude.ai"

    @property
    def chat_url(self) -> str:
        return "https://claude.ai/new"

    async def is_authenticated(self) -> bool:
        try:
            await self.session.navigate(self.chat_url)
            await self.session.wait_for_selector("div[contenteditable='true']", timeout=10000)
            return True
        except Exception:
            return False

    async def send_question(self, question: str, *, wait_time: float = 60) -> AIResponse:
        if not await self.is_authenticated():
            raise RuntimeError("Claude: sessão não autenticada. Faça login manualmente primeiro.")

        await self.session.navigate(self.chat_url)
        await asyncio.sleep(2)

        try:
            # Campo de input do Claude
            await self.session.wait_for_selector("div[contenteditable='true']", timeout=10000)
            await self.session.fill("div[contenteditable='true']", question)
            await asyncio.sleep(0.5)
            await self.session.press("div[contenteditable='true']", "Enter")
        except Exception as e:
            raise RuntimeError(f"Falha ao enviar pergunta: {e}")

        # Aguardar resposta - Claude usa streaming em div específica
        response_text = await self._wait_for_response(
            "div[data-testid*='assistant'], .font-claude, [data-message-author='assistant']",
            timeout=wait_time
        )

        cleaned = self._clean_response(response_text)

        return AIResponse(
            service="claude",
            question=question,
            answer=cleaned,
            model="claude-3-opus",
            raw_html=response_text,
        )


class AIServiceManager:
    """Gerenciador de serviços de IA - coordena múltiplos serviços."""

    def __init__(self, profile: BrowserProfile | None = None, *, headless: bool = True) -> None:
        self.profile = profile or BrowserProfile()
        self.headless = headless
        self._session: AuthenticatedBrowserSession | None = None
        self._services: dict[str, AIServiceBase] = {}

    async def initialize(self) -> None:
        """Inicializa sessão e serviços."""
        self._session = AuthenticatedBrowserSession(
            profile=self.profile,
            headless=self.headless,
        )
        await self._session.initialize()

        # Instanciar serviços
        self._services = {
            "chatgpt": ChatGPTService(self._session),
            "gemini": GeminiService(self._session),
            "claude": ClaudeService(self._session),
        }

    def get_service(self, name: str) -> AIServiceBase | None:
        """Obtém serviço por nome."""
        return self._services.get(name.lower())

    async def check_all_auth(self) -> dict[str, bool]:
        """Verifica autenticação de todos os serviços."""
        results = {}
        for name, service in self._services.items():
            try:
                results[name] = await service.is_authenticated()
            except Exception:
                results[name] = False
        return results

    async def query_all(
        self,
        question: str,
        *,
        services: list[str] | None = None,
        wait_time: float = 45,
    ) -> dict[str, AIResponse]:
        """Consulta múltiplos serviços em paralelo."""
        selected = services or list(self._services.keys())
        tasks = []

        for name in selected:
            service = self._services.get(name.lower())
            if service:
                tasks.append(self._query_service(name, service, question, wait_time))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = {}
        for i, name in enumerate(selected):
            result = results[i]
            if isinstance(result, Exception):
                output[name] = AIResponse(
                    service=name,
                    question=question,
                    answer=f"Erro: {result}",
                    metadata={"error": str(result)},
                )
            else:
                output[name] = result

        return output

    async def _query_service(
        self,
        name: str,
        service: AIServiceBase,
        question: str,
        wait_time: float,
    ) -> AIResponse:
        return await service.send_question(question, wait_time=wait_time)

    async def close(self) -> None:
        if self._session:
            await self._session.close()