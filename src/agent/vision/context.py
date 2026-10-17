# src/agent/vision/context.py — referências de imagem para modelos com visão
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from agent.security.paths import PathSecurityError, resolve_under_root


class ImageReference(BaseModel):
    path: str
    caption: str | None = None


class VisionContextBundle(BaseModel):
    images: list[ImageReference] = Field(default_factory=list)
    notes: str | None = None


def resolve_images(project_root: str, refs: list[ImageReference]) -> VisionContextBundle:
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
    return bool(profile.get("supports_vision"))
