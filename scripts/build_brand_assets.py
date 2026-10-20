#!/usr/bin/env python3
"""
Arquivo: scripts/build_brand_assets.py
Nome: build_brand_assets.py
Propósito: gerar os assets web da marca Callidus a partir dos SVG de media/.
Responsabilidade: camada de script — extrai as formas dos SVG de origem e escreve versões normalizadas em web/static/assets/brand/.
Componentes: extração de formas do SVG, conversão de polígono em caminho, escrita do SVG final, símbolo, wordmark, lockups e favicon.
Dependências: os SVG de media/ e a biblioteca padrão do Python (re, pathlib).
Observações: escreve apenas em web/static/assets/brand/ e não altera os arquivos de origem.


Gera os assets web da marca Callidus a partir dos SVG de `media/`.

Os arquivos de `media/` vêm do CorelDRAW: `viewBox` em centésimos de
milímetro, cores em classes CSS (`.fil0` = #F6F4F4, `.fil1` = #668DF7) e
glifos misturados entre `<path>` e `<polygon>`. Este script extrai as formas
completas, normaliza a escala e escreve versões limpas em
`web/static/assets/brand/`.

Uso: python scripts/build_brand_assets.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "media"
OUT = ROOT / "web" / "static" / "assets" / "brand"

INK = "#F6F4F4"
ACCENT = "#668DF7"

# Formas do símbolo, na ordem em que aparecem no arquivo de logo.
SHAPE_RE = re.compile(r"<(path|polygon)\s+class=\"(fil\d)\"[^>]*?\s(?:d|points)=\"([^\"]+)\"")


def shapes(svg: str) -> list[tuple[str, str, str]]:
    """Devolve [(tag, classe, conteúdo do atributo d/points)] na ordem do arquivo."""
    return [(m.group(1), m.group(2), m.group(3)) for m in SHAPE_RE.finditer(svg)]


def to_path(tag: str, cls: str, data: str) -> str:
    """Converte a forma em um `<path>` com `d` equivalente."""
    if tag == "polygon":
        pts = [float(v) for v in re.findall(r"-?\d*\.?\d+", data)]
        pairs = list(zip(pts[::2], pts[1::2]))
        first = pairs[0]
        rest = "".join(f"L{x:g} {y:g}" for x, y in pairs[1:])
        return f"M{first[0]:g} {first[1]:g}{rest}Z"
    return data


def write_svg(name: str, view_box: tuple[float, float, float, float], body: str, title: str = "Callidus") -> None:
    """Grava o SVG final com o viewBox, o tamanho e o título informados."""
    x, y, w, h = view_box
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x:g} {y:g} {w:g} {h:g}" '
        f'width="{w / 100:g}" height="{h / 100:g}" role="img" aria-label="{title}">\n'
        f"<title>{title}</title>\n{body}\n</svg>\n",
        encoding="utf-8",
    )


def main() -> None:
    """Extrai as formas dos quatro SVG de origem e escreve os assets finais da marca."""
    logo = shapes((MEDIA / "Callidus Logo.svg").read_text(encoding="utf-8"))
    name = shapes((MEDIA / "Callidus Name.svg").read_text(encoding="utf-8"))
    horiz = shapes((MEDIA / "Callidus Name + Logo Horizontal.svg").read_text(encoding="utf-8"))
    vert = shapes((MEDIA / "Callidus Name + Logo Vertical.svg").read_text(encoding="utf-8"))

    # --- símbolo: "C" hexagonal + estrela azul ---------------------------------
    # A versão com `<img>` usa cor fixa (a interface é dark-only); a versão
    # `currentColor` serve para o SVG inline em `app.js`, que herda a cor do tema.
    mark_fixed = "".join(
        f'<path d="{to_path(t, c, d)}" fill="{ACCENT if c == "fil1" else INK}"/>'
        for t, c, d in logo
    )
    mark_current = "".join(
        f'<path d="{to_path(t, c, d)}" fill="{ACCENT if c == "fil1" else "currentColor"}"/>'
        for t, c, d in logo
    )
    # O símbolo ocupa de x≈3116 a x≈18050 e y≈2054 a y≈18266 no viewBox original.
    write_svg("callidus-mark.svg", (3116, 2054, 14935, 16212), mark_fixed)
    write_svg("callidus-mark-current.svg", (3116, 2054, 14935, 16212), mark_current)

    # --- wordmark "Callidus" (só o nome) ---------------------------------------
    # Glifos de "Callidus" vão de x≈1397 a x≈19760, y≈495 a y≈2150.
    name_body = "".join(f'<path d="{to_path(t, c, d)}" fill="{INK}"/>' for t, c, d in name)
    write_svg("callidus-wordmark.svg", (1397, 495, 18363, 1655), name_body)

    # --- lockup horizontal: símbolo + nome -------------------------------------
    # No arquivo horizontal o símbolo vem em x≈2928..9703 e o nome em x≈12811..52634.
    gap = 2600
    logo_w = 9703 - 2928
    name_w = 52634 - 12811
    total_w = logo_w + gap + name_w
    body = "".join(
        f'<g transform="translate({-2928 if i < 2 else -12811 + logo_w + gap},0)">'
        f'<path d="{to_path(t, c, d)}" fill="{ACCENT if c == "fil1" else INK}"/>'
        f"</g>"
        for i, (t, c, d) in enumerate(horiz)
    )
    write_svg("callidus-lockup.svg", (0, 2937, total_w, 7355), body)

    # --- lockup vertical -------------------------------------------------------
    # No arquivo vertical o símbolo fica em y≈1309..8664 e o nome em y≈10266..10877.
    v_gap = 1400
    v_logo_h = 8664 - 1309
    v_logo_w = 14093 - 7317
    v_name_top = 10266
    v_name_h = 10877 - v_name_top
    v_name_w = 19768 - 1398
    v_total_w = max(v_logo_w, v_name_w)
    v_total_h = v_logo_h + v_gap + v_name_h
    body = "".join(
        f'<g transform="translate({-7317 if i < 2 else -1398},{-1309 if i < 2 else v_logo_h + v_gap - v_name_top})">'
        f'<path d="{to_path(t, c, d)}" fill="{ACCENT if c == "fil1" else INK}"/>'
        f"</g>"
        for i, (t, c, d) in enumerate(vert)
    )
    write_svg("callidus-lockup-vertical.svg", (0, 0, v_total_w, v_total_h), body)

    # --- favicon: símbolo sobre fundo escuro -----------------------------------
    fav_body = (
        f'<rect width="{14935}" height="{16212}" rx="3200" fill="#14161c"/>\n'
        f'<g transform="translate(2100,2600) scale(0.72)">\n'
        + "".join(
            f'<path d="{to_path(t, c, d)}" fill="{ACCENT if c == "fil1" else INK}"/>'
            for t, c, d in logo
        )
        + "\n</g>"
    )
    write_svg("favicon.svg", (0, 0, 14935, 16212), fav_body)

    for f in sorted(OUT.iterdir()):
        print(f"{f.name}  {f.stat().st_size} bytes")


if __name__ == "__main__":
    main()
