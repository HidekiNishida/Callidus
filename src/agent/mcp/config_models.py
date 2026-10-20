"""
Arquivo: src/agent/mcp/config_models.py
Nome: config_models.py
Propósito: definir os tipos de configuração dos servidores MCP.
Responsabilidade: camada de infraestrutura — contrato de configuração de um servidor MCP.
Componentes: McpServerConfig.
Dependências: dataclasses.
Observações: o comando é a lista completa (executável e argumentos); o ambiente é opcional.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class McpServerConfig:
    """Configuração de um servidor MCP acessado por stdio.

    Atributos:
        id: identificador do servidor, usado para prefixar as ferramentas (`mcp:<id>:<tool>`).
        command: executável e argumentos com que o servidor é iniciado.
        env: variáveis de ambiente passadas ao processo do servidor.
        enabled: quando `False`, o servidor não é iniciado.
    """

    id: str
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
