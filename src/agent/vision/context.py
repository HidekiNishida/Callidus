"""
Arquivo: src/agent/vision/context.py
Nome: context.py
Propósito: resolver as referências de imagem usadas em modelos com capacidade de visão.
Responsabilidade: camada de aplicação — filtragem e normalização dos anexos de imagem.
Componentes: ImageReference, VisionContextBundle, resolve_images, vision_supported.
Dependências: agent.security.paths, pydantic.
Observações: imagens fora da raiz do projeto ou de formato desconhecido são descartadas silenciosamente.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from agent.security.paths import PathSecurityError, resolve_under_root


class ImageReference(BaseModel):
    """Referência a uma imagem do projeto, com legenda opcional.

    Atributos:
        path: caminho da imagem, relativo à raiz do projeto ou absoluto.
        caption: legenda opcional enviada ao modelo.
    """

    path: str
    caption: str | None = None


class VisionContextBundle(BaseModel):
    """Conjunto de imagens resolvidas e as notas que acompanham o prompt.

    Atributos:
        images: imagens aceitas e já resolvidas em caminho absoluto.
        notes: observação sobre o uso das imagens no prompt.
    """

    images: list[ImageReference] = Field(default_factory=list)
    notes: str | None = None


def resolve_images(project_root: str, refs: list[ImageReference]) -> VisionContextBundle:
    """Resolve as referências de imagem, descartando as que não são válidas.

    Args:
        project_root: raiz do projeto, usada como escopo autorizado.
        refs: referências informadas na tarefa.

    Returns:
        O pacote de visão com as imagens aceitas e uma nota de uso.
    """
    resolved: list[ImageReference] = []
    for ref in refs:
        try:
            full = resolve_under_root(project_root, ref.path)
        except PathSecurityError:
            continue
        if full.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"} and full.is_file():
            resolved.append(ImageReference(path=str(full), caption=ref.caption))
    return VisionContextBundle(
        images=resolved,
        notes="Imagens omitidas do prompt se o modelo não suportar visão.",
    )


def vision_supported(profile: dict) -> bool:
    """Indica se o perfil do modelo aceita imagens.

    Args:
        profile: dicionário do perfil do modelo.

    Returns:
        `True` quando o perfil declara suporte a visão.
    """
    return bool(profile.get("supports_vision"))
