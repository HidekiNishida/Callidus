"""
Arquivo: src/agent/brand.py
Nome: brand.py
Propósito: definir a identidade do produto (nome, símbolo, aliases legados).
Responsabilidade: camada de apresentação — constantes de marca consumidas pela interface e pelas rotas.
Componentes: BRAND_NAME, BRAND_TAGLINE, caminhos dos assets de marca, aliases legados, is_attachments_dir().
Dependências: nenhuma.
Observações: os aliases legados (`.agente`, `agente-inbox://local`) são mantidos por compatibilidade de leitura.
"""
from __future__ import annotations

# Nome comercial exibido na interface, na documentação e nos metadados da API.
BRAND_NAME = "Callidus"

# Descrição curta usada em metadados (OpenAPI, pyproject, README).
BRAND_TAGLINE = "Agente de desenvolvimento otimizado para modelos locais pequenos"

# Símbolo: "C" hexagonal com estrela azul ao centro.
BRAND_MARK_PATH = "/assets/brand/callidus-mark.svg"
BRAND_LOCKUP_PATH = "/assets/brand/callidus-lockup.svg"
BRAND_LOCKUP_VERTICAL_PATH = "/assets/brand/callidus-lockup-vertical.svg"
BRAND_WORDMARK_PATH = "/assets/brand/callidus-wordmark.svg"
BRAND_FAVICON_PATH = "/assets/brand/favicon.svg"

# Pasta de anexos gravados dentro do projeto do usuário.
ATTACHMENTS_DIR = ".callidus"
LEGACY_ATTACHMENTS_DIR = ".agente"

# URI virtual da caixa de entrada local.
INBOX_ROOT = "callidus-inbox://local"
LEGACY_INBOX_ROOT = "agente-inbox://local"

# Identificador de preferência da UI (localStorage).
UI_STORAGE_KEY = "callidus-ui-v1"
LEGACY_UI_STORAGE_KEY = "agente-local-ui-v1"

# User-Agent das requisições HTTP feitas pelo agente.
USER_AGENT = "callidus"


def is_attachments_dir(rel: str) -> bool:
    """True quando o caminho relativo aponta para a pasta de anexos (nova ou legada)."""
    return rel.startswith(f"{ATTACHMENTS_DIR}/") or rel.startswith(f"{LEGACY_ATTACHMENTS_DIR}/")
