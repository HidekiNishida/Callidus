"""
Arquivo: src/agent/tools/contracts.py
Nome: contracts.py
Propósito: definir os contratos estáveis da camada de ferramentas (risco, permissões, execução).
Responsabilidade: camada de infraestrutura — vocabulário compartilhado entre registro, política e adaptadores.
Componentes: ToolRisk, ExecutionMode, ToolFamily, RiskOrder.
Dependências: enum.
Observações: os enums são textos; a serialização em log e API não depende de tipo fechado.
"""
from __future__ import annotations

from enum import Enum


class ToolRisk(str, Enum):
    """Nível de risco de uma ferramenta, do mais seguro ao mais perigoso.

    Atributos:
        READ: apenas lê e diagnostica; não altera nada.
        WRITE: altera o workspace autorizado.
        EXECUTE: executa comandos e aplicações.
        CONFIGURE: muda configuração do sistema ou do ambiente.
        PRIVILEGED: elevação de privilégio, exclusão irreversível ou envio a terceiros.
    """

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    CONFIGURE = "configure"
    PRIVILEGED = "privileged"


class ExecutionMode(str, Enum):
    """Como a ferramenta roda, do ponto de vista do agente.

    Atributos:
        FOREGROUND: bloqueia a etapa até devolver o resultado.
        BACKGROUND: devolve imediatamente; o resultado é consultado depois.
        INTERACTIVE: precisa de uma sessão gráfica ou de interação humana.
        NON_INTERACTIVE: roda sem interface; não depende de tela.
    """

    FOREGROUND = "foreground"
    BACKGROUND = "background"
    INTERACTIVE = "interactive"
    NON_INTERACTIVE = "non_interactive"


class ToolFamily(str, Enum):
    """Família funcional da ferramenta — a unidade habilitada e desabilitada em conjunto.

    Atributos:
        FILE: leitura e escrita de arquivos.
        COMMAND: execução de comandos e processos.
        SYSTEM: diagnóstico do sistema, aplicativos e rede.
        DESKTOP: mouse, teclado, tela e acessibilidade.
        BROWSER: automação de páginas web.
        ENGINEERING: descoberta de projeto, git, lint, build e testes.
        SKILL: autoria e ciclo de vida das skills.
        AUTOMATION: tarefas agendadas já existentes.
        MEMORY: memórias do projeto e da conversa.
    """

    FILE = "file"
    COMMAND = "command"
    SYSTEM = "system"
    DESKTOP = "desktop"
    BROWSER = "browser"
    ENGINEERING = "engineering"
    SKILL = "skill"
    AUTOMATION = "automation"
    MEMORY = "memory"


#: Ordem crescente de risco — usada para comparar níveis sem depender do enum.
RISK_ORDER: dict[str, int] = {
    ToolRisk.READ.value: 0,
    ToolRisk.WRITE.value: 1,
    ToolRisk.EXECUTE.value: 2,
    ToolRisk.CONFIGURE.value: 3,
    ToolRisk.PRIVILEGED.value: 4,
}


def risk_at_least(risk: str | ToolRisk, minimum: str | ToolRisk) -> bool:
    """Indica se um nível de risco atinge um piso.

    Args:
        risk: nívelAvaliado.
        minimum: piso de comparação.

    Returns:
        `True` quando `risk` é igual ou superior a `minimum`.
    """
    current = RISK_ORDER.get(risk.value if isinstance(risk, ToolRisk) else str(risk), 0)
    floor = RISK_ORDER.get(minimum.value if isinstance(minimum, ToolRisk) else str(minimum), 0)
    return current >= floor


def risk_above(risk: str | ToolRisk, ceiling: str | ToolRisk) -> bool:
    """Indica se um nível de risco ultrapassa um teto.

    O teto é o nível mais alto que roda sem aprovação; o nível imediatamente acima já
    exige aprovação explícita.

    Args:
        risk: nível avaliado.
        ceiling: teto de comparação.

    Returns:
        `True` quando `risk` é estritamente maior que `ceiling`.
    """
    current = RISK_ORDER.get(risk.value if isinstance(risk, ToolRisk) else str(risk), 0)
    limit = RISK_ORDER.get(ceiling.value if isinstance(ceiling, ToolRisk) else str(ceiling), 0)
    return current > limit
