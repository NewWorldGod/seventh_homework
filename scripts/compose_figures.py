# -*- coding: utf-8 -*-
"""Compose the report figures from the individual renders.

fig_controls.png   clay | depth | normal (512 set)
fig_ab.png         run A (512) | run B (768), same display height
fig_ablation.png   A (cn 0.9) | D (cn 0.5) | F (cn 0.0) | E (cfg 7.0)
"""
from __future__ import annotations

import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output")
FONT = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size)


def panel(img: Image.Image, label: str, height: int, pad: int = 10) -> Image.Image:
    scale = height / img.height
    img = img.convert("RGB").resize((int(img.width * scale), height), Image.LANCZOS)
    f = font(22)
    lines = label.split("\n")
    line_h = 30
    canvas = Image.new("RGB", (img.width + pad * 2, height + pad * 2 + line_h * len(lines)), "white")
    canvas.paste(img, (pad, pad))
    draw = ImageDraw.Draw(canvas)
    for i, line in enumerate(lines):
        w = draw.textlength(line, font=f)
        draw.text(((canvas.width - w) / 2, height + pad + 4 + i * line_h), line, fill=(30, 30, 30), font=f)
    draw.rectangle([pad - 1, pad - 1, pad + img.width, pad + img.height], outline=(160, 160, 160), width=1)
    return canvas


def hstack(panels: list[Image.Image], gap: int = 18) -> Image.Image:
    h = max(p.height for p in panels)
    w = sum(p.width for p in panels) + gap * (len(panels) - 1)
    canvas = Image.new("RGB", (w, h), "white")
    x = 0
    for p in panels:
        canvas.paste(p, (x, 0))
        x += p.width + gap
    return canvas


def run(name: str) -> dict:
    with open(os.path.join(OUT, f"{name}_run.json"), encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    controls = hstack(
        [
            panel(Image.open(os.path.join(OUT, "demo_clay.png")), "白模 clay", 420),
            panel(Image.open(os.path.join(OUT, "demo_depth_0001.png")), "深度 depth（近亮远暗）", 420),
            panel(Image.open(os.path.join(OUT, "demo_normal_0001.png")), "法线 normal（n×0.5+0.5）", 420),
        ]
    )
    controls.save(os.path.join(OUT, "fig_controls.png"))

    a = run("a512")
    b = run("b768")
    ab = hstack(
        [
            panel(Image.open(os.path.join(OUT, "a512_photoreal.png")),
                  f"A：512² / 4 步\n采样 {a['sample_s']:.1f}s + VAE {a['vae_s']:.1f}s", 460),
            panel(Image.open(os.path.join(OUT, "b768_photoreal.png")),
                  f"B：768² / 4 步\n采样 {b['sample_s']:.1f}s + VAE {b['vae_s']:.1f}s", 460),
        ]
    )
    ab.save(os.path.join(OUT, "fig_ab.png"))

    metrics = {}
    mpath = os.path.join(OUT, "metrics.json")
    if os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as fh:
            metrics = {r["name"]: r for r in json.load(fh)["runs"]}

    def abl(name: str, title: str) -> Image.Image:
        r = run(name)
        extra = ""
        m = metrics.get(name)
        if m:
            extra = f"深度回测 ρ={m['depth_spearman']:.2f} / 倒角 {m['edge_chamfer_depth_to_photo_px']:.1f}px"
        return panel(Image.open(os.path.join(OUT, f"{name}_photoreal.png")),
                     f"{title}\n{extra}", 340)

    a_rho = metrics.get("a512", {}).get("depth_spearman", 0.0)
    g_rho = metrics.get("g_prompt", {}).get("depth_spearman", 0.0)
    prompt_cmp = hstack(
        [
            panel(Image.open(os.path.join(OUT, "a512_photoreal.png")),
                  f"A：指南提示词 / 4 步\n深度回测 ρ={a_rho:.2f}", 420),
            panel(Image.open(os.path.join(OUT, "g_prompt_photoreal.png")),
                  f"G：细化提示词 / 6 步\n深度回测 ρ={g_rho:.2f}", 420),
        ]
    )
    prompt_cmp.save(os.path.join(OUT, "fig_prompt.png"))

    ablation = hstack(
        [abl("a512", "A：control 0.9 / CFG 1.2"), abl("d_cn05", "D：control 0.5 / CFG 1.2")],
        gap=18,
    )
    ablation2 = hstack(
        [abl("f_cn00", "F：control 0.0（无控制）"), abl("e_cfg7", "E：control 0.9 / CFG 7.0")],
        gap=18,
    )
    canvas = Image.new("RGB", (ablation.width, ablation.height + ablation2.height + 18), "white")
    canvas.paste(ablation, (0, 0))
    canvas.paste(ablation2, (0, ablation.height + 18))
    canvas.save(os.path.join(OUT, "fig_ablation.png"))

    print("figures written:", ", ".join(["fig_controls.png", "fig_ab.png", "fig_prompt.png", "fig_ablation.png"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
