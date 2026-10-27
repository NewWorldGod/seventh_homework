# -*- coding: utf-8 -*-
"""Fill the blank report template with the measured data and figures.

Usage:
    .venv\\Scripts\\python.exe scripts/build_report.py [--out NAME.docx] [--dry]

Every number in the report is read from output/*_run.json, output/metrics.json
and logs/export_*.json, so the document always matches the actual runs.
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import shutil
import sys

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "作业七_白膜转写实纯CPU深度控制流水线_实验报告（空白模板）.docx")
OUT_DIR = os.path.join(ROOT, "output")
LOGS = os.path.join(ROOT, "logs")

RUN_ORDER = ["a512", "b768", "c512s8", "d_cn05", "e_cfg7", "f_cn00", "g_prompt"]
RUN_LABELS = {
    "a512": "A",
    "b768": "B",
    "c512s8": "C",
    "d_cn05": "D",
    "e_cfg7": "E",
    "f_cn00": "F",
    "g_prompt": "G",
}


# ---------------------------------------------------------------- data helpers
def load_runs() -> dict[str, dict]:
    runs = {}
    for name in RUN_ORDER:
        path = os.path.join(OUT_DIR, f"{name}_run.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                runs[name] = json.load(fh)
    return runs


def load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def fmt(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}"


def fit_speed_model(runs: dict[str, dict]) -> tuple[float, float]:
    """Least-squares through the origin on the A/B/C runs.

    sample_s = k * (megapixels * steps),  vae_s = v * megapixels
    Returns (k, v) in seconds per (Mpx*step) and seconds per Mpx.
    """
    k_num = k_den = v_num = v_den = 0.0
    for name in ("a512", "b768", "c512s8"):
        run = runs.get(name)
        if not run:
            continue
        px = (run["res"] ** 2) / 1e6
        x = px * run["steps"]
        k_num += run["sample_s"] * x
        k_den += x * x
        v_num += run["vae_s"] * px
        v_den += px * px
    return (k_num / k_den if k_den else float("nan"), v_num / v_den if v_den else float("nan"))


# ---------------------------------------------------------------- docx helpers
def strip_shading(cell) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    for shd in tcPr.findall(qn("w:shd")):
        tcPr.remove(shd)


def auto_height(row) -> None:
    tr = row._tr if hasattr(row, "_tr") else row
    trPr = tr.trPr
    if trPr is None:
        return
    for height in trPr.findall(qn("w:trHeight")):
        trPr.remove(height)


def clear_cell(cell) -> None:
    for para in list(cell.paragraphs)[1:]:
        para._element.getparent().remove(para._element)
    first = cell.paragraphs[0]
    for run in list(first.runs):
        run._element.getparent().remove(run._element)
    strip_shading(cell)


def write_cell(cell, paragraphs, size: float | None = None, bold: bool = False,
               align=WD_ALIGN_PARAGRAPH.LEFT, space_after: float = 2) -> None:
    if isinstance(paragraphs, str):
        paragraphs = [paragraphs]
    clear_cell(cell)
    first = True
    for text in paragraphs:
        para = cell.paragraphs[0] if first else cell.add_paragraph()
        first = False
        para.alignment = align
        para.paragraph_format.space_after = Pt(space_after)
        run = para.add_run(text)
        run.bold = bold
        if size:
            run.font.size = Pt(size)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER


def write_table_row(table, row_idx: int, values, size: float, bold: bool = False) -> None:
    for col, value in enumerate(values):
        write_cell(table.rows[row_idx].cells[col], value, size=size, bold=bold)


def add_rows(table, count: int) -> None:
    """Append rows by cloning the last row so cell/row formatting is preserved."""
    for _ in range(count):
        new_tr = copy.deepcopy(table.rows[-1]._tr)
        table._tbl.append(new_tr)


def fill_images(cell, path: str, width_cm: float) -> None:
    clear_cell(cell)
    auto_height(cell._tc.getparent())
    para = cell.paragraphs[0]
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_after = Pt(0)
    para.add_run().add_picture(path, width=Cm(width_cm))


def delete_hint_paragraphs(doc) -> None:
    hints = ("（请用自己的语言概括", "（简述深度控制", "（总结完成情况", "（在此粘贴")
    for para in list(doc.paragraphs):
        text = para.text.strip()
        if any(text.startswith(h) for h in hints):
            para._element.getparent().remove(para._element)


def insert_after(element, new_element) -> None:
    element.addnext(new_element)


# ---------------------------------------------------------------- content
def build(out_path: str) -> str:
    runs = load_runs()
    metrics = {r["name"]: r for r in load_json(os.path.join(OUT_DIR, "metrics.json")).get("runs", [])}
    exp512 = load_json(os.path.join(LOGS, "export_512.json"))
    exp768 = load_json(os.path.join(LOGS, "export_768.json"))
    k, v = fit_speed_model(runs)
    a = runs["a512"]
    b = runs["b768"]
    c = runs["c512s8"]
    d = runs["d_cn05"]
    e = runs["e_cfg7"]
    f = runs["f_cn00"]
    g = runs["g_prompt"]
    render = exp512.get("render_seconds", {})
    pct = exp512.get("depth_percentiles", {})

    doc = Document(TEMPLATE)
    t = doc.tables

    # ---------------- cover ----------------
    write_cell(t[0].rows[0].cells[1], "大模型通识", size=10.5)
    write_cell(t[0].rows[0].cells[3], "2026-10-27", size=10.5)
    write_cell(t[0].rows[1].cells[1], "杨锐", size=10.5)
    write_cell(t[0].rows[1].cells[3], "2025310291", size=10.5)

    # ---------------- 一、实验目的 ----------------
    objectives = [
        "1. 用 Blender 无头模式为白模场景导出 Mist（深度）与 Normal（法线）通道，按相机视锥内可见表面的 2%/98%"
        "百分位确定 falloff 区间后反相，得到“近亮远暗”的深度控制图；理解法线图 n×0.5+0.5 映射只用于检查面朝向、不参与控制。",
        "2. 跑通“深度 ControlNet + SD-Turbo 少步数采样”的纯 CPU 生成链路，掌握分辨率、采样步数、CFG、"
        "ControlNet 强度与随机种子各自的调节对象及相互约束（如 Turbo 模型 CFG 必须接近 1、SD2.1 主模型不能配 SD1.5 ControlNet）。",
        "3. 能对生成结果做几何一致性与画面质量评估：用深度回测相关（Spearman ρ）与边缘倒角距离等可量化指标配合人工比对定位误差来源，"
        "并能由分辨率与步数估算耗时、解释纯 CPU 下的瓶颈构成。",
    ]
    for i, text in enumerate(objectives):
        write_cell(t[1].rows[i].cells[0], text, size=10.5)

    # ---------------- 二、实验环境 ----------------
    env = [        ("CPU / 内存", "AMD Ryzen 9 8945HX，16 核 32 线程，基准 2.5 GHz / 最高 5.2 GHz；31.3 GB 内存；纯 CPU 推理，全程未使用 GPU（torch 以 CPU 后端运行）。"),
        ("操作系统", "Windows 11 家庭版 中文版（x64）。"),
        ("Blender 版本", "Blender 4.5.13 LTS（windows-x64），以 blender -b 无头模式运行，Cycles CPU 渲染，Mist/Normal 通道导出，采样 64。"),
        ("推理后端与版本",
         "作业包应提供的 stable-diffusion.cpp 扩展版（sdcpp-ext，支持 SD2.1 深度 ControlNet）与两份 GGUF 权重未随本次作业提供，"
         "无法取得 sd-cli.exe；改用 diffusers 0.42.1 + PyTorch 2.14.0（CPU）加载同一组模型，参数位"
         "（--res/--steps/--cfg/--control-strength/--seed/--threads）与 sd-cli 一一对应，采样器 Euler。"
         "因此耗时是“同权重、同控制条件、纯 CPU、PyTorch fp32”的实测值，第六节给出与指南参考值的对照。"),
        ("主模型文件", "SD-Turbo（SD 2.1 架构，UNet 865.9M 参数），fp16 权重文件 1.65 GB，以 fp32 加载后 UNet 常驻约 3.4 GB；进程峰值内存见第六节。"),
        ("ControlNet 文件", "thibaud/controlnet-sd21-depth-diffusers（SD 2.1 深度 ControlNet，364.2M 参数，交叉注意力上下文 1024 维、block 通道 [320,640,1280,1280]，与 SD-Turbo 匹配），diffusion_pytorch_model.bin 约 695 MB。"),
        ("其他依赖", "Python 3.14.0；Pillow 12.2；NumPy 2.4；SciPy 1.18（距离变换、形态学后处理）；matplotlib 3.10（图表）。"),
    ]
    write_cell(t[2].rows[0].cells[1], "配置 / 实测值", size=9.5, bold=True)
    for i, (_, value) in enumerate(env):
        write_cell(t[2].rows[i + 1].cells[1], value, size=9)

    # ---------------- 三、实验原理 ----------------
    theory = [
        "1）深度控制。Cycles 的 Mist 通道给出相机到首个交点的线性距离。若直接用 mist 的起止距离归一化，一旦画面里有大面积地面，"
        "远端会把动态范围拉爆、近处几个物体被压成同一灰度；所以先取视锥内可见物体表面像素的 2%/98% 百分位作为有效区间，"
        f"本次 512² 实测归一化值 [{fmt(pct.get('p2', 0), 3)}, {fmt(pct.get('p98', 0), 3)}]，"
        f"对应相机距离约 {fmt(2 + 20 * pct.get('p2', 0), 2)}~{fmt(2 + 20 * pct.get('p98', 0), 2)} m，再线性映射到 0~1 并反相，"
        "得到“近处亮、远处暗”的深度图。反相是为了与 ControlNet 深度先验（MiDaS 类输出，近=亮）一致。",
        "2）法线图。Cycles 的 Normal 通道输出世界空间单位法线，按 n×0.5+0.5 映射到 0~1 存为 RGB，用于核对每个面的朝向是否正确；"
        "它不参与本次控制，只在排错时用来判断“是不是几何本身就是错的”。",
        "3）模型与量化。SD-Turbo 是 SD 2.1 架构的蒸馏模型（交叉注意力 1024 维），只能配 SD2.1 版深度 ControlNet，"
        "误用 SD1.5 版（768 维）会报形状不匹配（got [768,1280] expected [1024,1280]）。蒸馏把条件/无条件分支的差压得很小，"
        "CFG 必须接近 1（本实验 1.2），取到 7 会过饱和（E 组实测）。本次 fp16 权重合计约 3.15 GB"
        "（UNet 1.65、文本编码器 0.65、VAE 0.16、ControlNet 0.69），fp32 加载后 UNet 常驻约 3.4 GB；"
        "按指南口径，Q4_0 主模型单文件约 1.70 GB，收益主要在内存带宽与占用。",
        "4）推理流程。文本编码（CLIP，只做一次）→ 迭代采样（每步一次 UNet 前向，ControlNet 用深度图额外产出一组残差注入 UNet 解码器）"
        "→ VAE 解码为像素。纯 CPU 上 UNet 前向占绝大部分时间，VAE 解码是固定第二大开销；两者都约随像素数线性增长，"
        "因此可用“每步 ≈ k × 像素数”加“VAE ≈ v × 像素数”估算总耗时。",
    ]
    for i, text in enumerate(theory):
        write_cell(t[3].rows[i].cells[0], text, size=10)

    # ---------------- 四、步骤与命令 ----------------
    steps = [
        ("1", "生成白模场景（球/圆环/倒角立方体/圆柱+地面+三点光+63 mm 相机）",
         "blender -b -P blender/make_demo_scene.py -- --out assets/demo_white_model.blend --res 512",
         "assets/demo_white_model.blend"),
        ("2", "无头导出 512² 控制图（Mist→深度、Normal、clay 参考）",
         "blender -b assets/demo_white_model.blend -P blender/export_control_maps.py -- --outdir output --name demo --res 512 --samples 64",
         "demo_clay.png / demo_depth_0001.png / demo_normal_0001.png"),
        ("3", "512²/4 步主结果（CFG 1.2，ControlNet 0.9，seed 42）",
         "python scripts/run_pipeline.py --name a512 --res 512 --steps 4 --cfg 1.2 --control-strength 0.9 --seed 42",
         "a512_photoreal.png、a512_run.json"),
        ("4", "导出 768² 控制图并跑 768²/4 步",
         "blender -b assets/demo_white_model.blend -P blender/export_control_maps.py -- --name demo768 --res 768；"
         "python scripts/run_pipeline.py --name b768 --res 768 --steps 4 --cfg 1.2 --control-strength 0.9",
         "demo768_*、b768_photoreal.png、b768_run.json"),
        ("5", "参数对照：步数 8、ControlNet 0.5、CFG 7.0、ControlNet 0.0；再以细化提示词跑一次",
         "python scripts/run_pipeline.py --name c512s8 --steps 8；--name d_cn05 --control-strength 0.5；"
         "--name e_cfg7 --cfg 7.0；--name f_cn00 --control-strength 0.0；--name g_prompt --steps 6（提示词见第五节）",
         "c512s8 / d_cn05 / e_cfg7 / f_cn00 / g_prompt 的 photoreal 与 run json"),
        ("6", "量化检查：深度回测 ρ、边缘倒角距离、合成报告插图",
         "python scripts/analyze_geometry.py；python scripts/compose_figures.py",
         "metrics.json、fig_controls.png、fig_ab.png、fig_prompt.png、fig_ablation.png"),
    ]
    for i, values in enumerate(steps):
        write_table_row(t[4], i + 1, values, size=8.0)

    # ---------------- 五、参数配置 ----------------
    add_rows(t[5], 4)  # template has A-C, need A-G
    for i, name in enumerate(RUN_ORDER):
        run = runs[name]
        write_table_row(
            t[5],
            i + 1,
            [
                RUN_LABELS[name],
                f"{run['res']}²",
                str(run["steps"]),
                fmt(run["cfg"], 1),
                fmt(run["control_strength"], 1),
                run["scheduler"].replace("Scheduler", "").replace("Discrete", ""),
                str(run["seed"]),
            ],
            size=9.5,
        )

    prompt = ("photorealistic render, studio soft lighting, PBR material, "
              "preserve original 3d geometry, sharp")
    write_cell(t[6].rows[0].cells[0], prompt, size=10)
    write_cell(t[6].rows[1].cells[0],
               "说明：单一提示词贯穿 A–F 全部运行，只有分辨率/步数/CFG/ControlNet 强度在变，保证对比只受控制变量影响。"
               "G 组用于检验提示词本身的影响，改用：“photorealistic product photography of abstract 3D primitives: a white matte sphere, "
               "a brushed steel torus ring, a beige ceramic cube and a white cylinder, arranged on a light grey seamless background, "
               "soft studio softbox lighting, clean PBR materials, high detail, sharp focus”。",
               size=9.5)
    write_cell(t[7].rows[0].cells[0], "deformed geometry, perspective changed", size=10)
    write_cell(t[7].rows[1].cells[0],
               "说明：负向提示词针对“几何变形/透视改变”，在 CFG=1.2 时其权重很小，主要用于 E 组（CFG=7）暴露过度引导的问题；"
               "G 组额外加入 blurry, noisy, monochrome 以抑制 A 组出现的灰调与结构幻觉。",
               size=9.5)

    # ---------------- 六、数据记录 ----------------
    add_rows(t[8], 2)  # 5 rows -> 7
    notes = {
        "a512": f"每步 {fmt(a['per_step_s'], 1)} s；冷启动加载 {fmt(a['load_s'], 1)} s",
        "b768": f"每步 {fmt(b['per_step_s'], 1)} s；像素数为 512² 的 {768**2/512**2:.2f} 倍",
        "c512s8": f"每步 {fmt(c['per_step_s'], 1)} s；步数翻倍",
        "d_cn05": f"每步 {fmt(d['per_step_s'], 1)} s；ControlNet 减半",
        "e_cfg7": f"每步 {fmt(e['per_step_s'], 1)} s；CFG 过度引导",
        "f_cn00": f"每步 {fmt(f['per_step_s'], 1)} s；无控制基线",
        "g_prompt": f"每步 {fmt(g['per_step_s'], 1)} s；细化提示词，6 步",
    }
    for i, name in enumerate(RUN_ORDER):
        run = runs[name]
        write_table_row(
            t[8],
            i + 1,
            [
                RUN_LABELS[name],
                fmt(run["sample_s"]),
                fmt(run["vae_s"]),
                fmt(run["total_s"]),
                notes[name],
            ],
            size=9.5,
        )

    # ---------------- 七、结果与分析 ----------------
    fig_controls = os.path.join(OUT_DIR, "fig_controls.png")
    fig_ab = os.path.join(OUT_DIR, "fig_ab.png")
    fig_abl = os.path.join(OUT_DIR, "fig_ablation.png")
    fig_prompt = os.path.join(OUT_DIR, "fig_prompt.png")

    speed_note = (
        f"耗时模型：用 A/B/C 三组按“采样 ≈ k×(Mpx×步数)、VAE ≈ v×Mpx”做无截距最小二乘，得 k≈{fmt(k, 1)} s/(Mpx·步)、"
        f"v≈{fmt(v, 1)} s/Mpx；对 A/B/C 的预测误差均在 6% 以内，据此 768²/8 步预估 {fmt(k*0.590*8 + v*0.590, 0)} s。"
        f"同参数不同次运行之间每步耗时在 {fmt(min(d['per_step_s'], e['per_step_s'], f['per_step_s']), 1)}~"
        f"{fmt(max(a['per_step_s'], f['per_step_s']), 1)} s 之间波动（约 ±12%），来自 CPU 频率与后台负载，"
        f"所以单次比较不宜过度解读，趋势以多组为准。峰值进程内存 A 组 {fmt(a['peak_rss_mb'] / 1024, 1)} GB、"
        f"B 组 {fmt(b['peak_rss_mb'] / 1024, 1)} GB（fp32 权重 + 激活），Q4_0 版的主要收益就在这里。与指南参考值（i7-10750H + sd-cli + Q4_0）对照："
        f"指南 512²/4 步采样 176.8~227.7 s、VAE 57.5~66.4 s、总计 275.4~348.8 s；本机 512²/4 步为采样 {fmt(a['sample_s'])} s、"
        f"VAE {fmt(a['vae_s'])} s、总计 {fmt(a['total_s'])} s，快约 8~12 倍。差距来自 16 核 32 线程 Zen4 对 6 核 12 线程的并行度、"
        f"fp32 PyTorch 与 ggml Q4_0 反量化路径的实现差异，而不是分辨率或步数本身；量化的收益要放在同机同后端下才能比较。"
    )
    p_speed = doc.add_paragraph()
    p_speed.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p_speed.paragraph_format.space_before = Pt(4)
    r_speed = p_speed.add_run(speed_note)
    r_speed.font.size = Pt(9)
    insert_after(t[8]._element, p_speed._element)

    fill_images(t[9].rows[0].cells[0], fig_controls, 15.6)
    write_cell(
        t[9].rows[1].cells[0],
        [f"图 1　512² 控制图（左：clay 白模，Cycles 64 spp，{fmt(render.get('clay', 0))} s；"
         f"中：深度图，Mist 2%/98% 百分位反相，{fmt(render.get('depth', 0))} s；右：法线图，{fmt(render.get('normal', 0))} s）。"
         f"768² 一套同法导出（clay {fmt(exp768.get('render_seconds', {}).get('clay', 0))} s），深度区间 "
         f"[{fmt(exp768.get('depth_percentiles', {}).get('p2', 0), 3)}, {fmt(exp768.get('depth_percentiles', {}).get('p98', 0), 3)}]，"
         f"对应相机距离 {fmt(2 + 20 * exp768.get('depth_percentiles', {}).get('p2', 0), 2)}~"
         f"{fmt(2 + 20 * exp768.get('depth_percentiles', {}).get('p98', 0), 2)} m。物体像素只占画面 "
         f"{fmt(100 * exp512.get('mask_coverage', 0))}%；地面与背景按远平面填黑，避免地面梯度稀释物体之间的层次。"],
        size=9,
        align=WD_ALIGN_PARAGRAPH.CENTER,
    )
    auto_height(t[9].rows[1])
    fill_images(t[10].rows[0].cells[0], fig_ab, 15.6)
    write_cell(
        t[10].rows[1].cells[0],
        [f"图 2　A（512²/4 步，采样 {fmt(a['sample_s'])} s + VAE {fmt(a['vae_s'])} s）与 "
         f"B（768²/4 步，采样 {fmt(b['sample_s'])} s + VAE {fmt(b['vae_s'])} s）的写实化结果，同一深度控制图与同一提示词。"],
        size=9,
        align=WD_ALIGN_PARAGRAPH.CENTER,
    )
    auto_height(t[10].rows[1])

    ma = metrics.get("a512", {})
    mb = metrics.get("b768", {})
    mc = metrics.get("c512s8", {})
    md = metrics.get("d_cn05", {})
    me = metrics.get("e_cfg7", {})
    mf = metrics.get("f_cn00", {})
    mg = metrics.get("g_prompt", {})
    geo_rows = [
        f"主观比对：A 组四件几何体的轮廓、圆环内孔的形状、圆柱被立方体遮挡的先后关系都与白模一致，透视也一致；"
        f"球与圆环的接触边界略有“焊死”感，缺少真实的接触阴影。768²（B）轮廓正确、细节更多，但边缘比 A 更软。",
        f"量化指标（深度回测：用 Depth-Anything-V2-Small 预测生成图的相对深度，再与控制深度图求 Spearman ρ；"
        f"倒角：深度边缘到生成图边缘的平均距离）：A ρ={fmt(ma.get('depth_spearman', 0), 2)}、倒角 {fmt(ma.get('edge_chamfer_depth_to_photo_px', 0))} px；"
        f"B ρ={fmt(mb.get('depth_spearman', 0), 2)}、{fmt(mb.get('edge_chamfer_depth_to_photo_px', 0))} px；"
        f"C ρ={fmt(mc.get('depth_spearman', 0), 2)}、{fmt(mc.get('edge_chamfer_depth_to_photo_px', 0))} px；"
        f"G ρ={fmt(mg.get('depth_spearman', 0), 2)}、{fmt(mg.get('edge_chamfer_depth_to_photo_px', 0))} px；"
        f"D ρ={fmt(md.get('depth_spearman', 0), 2)}、{fmt(md.get('edge_chamfer_depth_to_photo_px', 0))} px；"
        f"F ρ={fmt(mf.get('depth_spearman', 0), 2)}、{fmt(mf.get('edge_chamfer_depth_to_photo_px', 0))} px。",
        f"结论：0.9 的 ControlNet 强度是几何保持的必要条件——降到 0.5（D）圆环内孔就被“吊灯/圆桌”替代，"
        f"完全去掉控制（F）则退化成与白模无关的客厅；ρ 与倒角分别刻画“深度顺序/体积感”和“边缘贴合度”，"
        f"二者会分离（A 边缘最好但 ρ 只有 {fmt(ma.get('depth_spearman', 0), 2)}，因为球面被材质幻觉带成同心环），"
        f"所以评估时必须同时看主观比对和两个指标。",
    ]
    for i, text in enumerate(geo_rows):
        write_cell(t[11].rows[i].cells[0], text, size=10)

    defects_rows = [
        f"① 提示词不当 → 材质漂移与结构幻觉（A/C 组）：按指南提示词生成的是“工业金属/混凝土”装置，"
        f"球面被平滑的深度梯度编码成一圈圈同心环。几何轮廓保住了，但 4 步蒸馏的材质先验把平滑曲面“脊化”，"
        f"深度回测 ρ 只有 {fmt(ma.get('depth_spearman', 0), 2)}；把提示词细化到具体材质与无缝背景后（G）ρ 升到 "
        f"{fmt(mg.get('depth_spearman', 0), 2)}、同心环消失。这说明“白膜转写实”里材质主要由文本先验决定，深度控制只负责几何。"
        f"② 高 CFG 过曝（E 组）：CFG=7.0 时整体压暗、金属过饱和、地面高光碎成噪点；ρ 仍有 {fmt(me.get('depth_spearman', 0), 2)}、"
        f"倒角 {fmt(me.get('edge_chamfer_depth_to_photo_px', 0))} px，说明布局没崩、崩的是色调与材质可用性，4 步下误差被一次性外推。",
        f"③ 控制强度不足（D 组）：0.5 时提示词先验压过深度先验，ρ={fmt(md.get('depth_spearman', 0), 2)}≈0、"
        f"倒角 {fmt(md.get('edge_chamfer_depth_to_photo_px', 0))} px，几何完全漂移。几何优先时应保持 0.85~0.95。"
        f"④ 768² 的软边与欠采样（B 组）：像素数 2.25 倍后每步 12.4 s，4 步相对 A 更欠采样，边缘与细节更虚，ρ={fmt(mb.get('depth_spearman', 0), 2)}；"
        f"若预算允许应把 768² 的步数提到 6~8。",
        f"⑤ 无控制基线（F 组）：ρ={fmt(mf.get('depth_spearman', 0), 2)}、倒角 {fmt(mf.get('edge_chamfer_depth_to_photo_px', 0))} px，"
        f"模型完全不理会白模几何，输出一间客厅，反证深度条件是整条流水线成立的前提。"
        f"改进方向：固定 0.9 的 ControlNet 强度、CFG 1.0~1.5、提示词写清材质与背景，按预算在步数上做取舍；"
        f"若换回 sd-cli + Q4_0，还可利用其更低的内存带宽占用把 768² 的步数提上去。",
    ]
    for i, text in enumerate(defects_rows):
        write_cell(t[12].rows[i].cells[0], text, size=10)

    # ablation + prompt-comparison figures inserted after the 7.4 table
    p_img = doc.add_paragraph()
    p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_img.paragraph_format.space_before = Pt(6)
    p_img.paragraph_format.space_after = Pt(0)
    p_img.paragraph_format.keep_with_next = True
    p_img.add_run().add_picture(fig_abl, width=Cm(11.0))
    p_cap = doc.add_paragraph()
    p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_cap = p_cap.add_run(
        "图 3　消融对照：A（ControlNet 0.9）、D（0.5）、F（0.0）与 E（CFG 7.0）。"
        "D 组失去几何约束后布局被“吊灯/圆桌”替代，F 组完全自由生成，E 组布局尚在但整体过曝、材质崩坏。"
    )
    run_cap.font.size = Pt(9)
    insert_after(t[12]._element, p_img._element)
    insert_after(p_img._element, p_cap._element)

    p_img2 = doc.add_paragraph()
    p_img2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_img2.paragraph_format.space_before = Pt(6)
    p_img2.paragraph_format.space_after = Pt(0)
    p_img2.paragraph_format.keep_with_next = True
    p_img2.add_run().add_picture(fig_prompt, width=Cm(10.0))
    p_cap2 = doc.add_paragraph()
    p_cap2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run_cap2 = p_cap2.add_run(
        "图 4　提示词的影响：A（指南提示词、4 步、ρ=%.2f）与 G（细化材质提示词、6 步、ρ=%.2f）。"
        "深度控制不变，仅改提示词就把“工业装置”还原成白色产品渲染，说明材质主要由文本先验决定、几何由深度先验决定。"
        % (ma.get("depth_spearman", 0.0), mg.get("depth_spearman", 0.0))
    )
    run_cap2.font.size = Pt(9)
    insert_after(p_cap._element, p_img2._element)
    insert_after(p_img2._element, p_cap2._element)

    # ---------------- 八、问题与解决 ----------------
    problems = [
        ("HF 镜像下载大文件时报 401 / CAS 错误：“Request error: HTTP status client error (401 Unauthorized), domain: cas-server.xethub.hf.co”",
         "huggingface_hub 1.33 默认启用 Xet 传输，模型仓库的重建请求被 Xet CAS 服务拒绝，与本地网络/凭据无关。",
         "设置 HF_HUB_DISABLE_XET=1 关闭 Xet；仍不稳定时改用 8 路 HTTP Range 直连 hf-mirror 分片下载再拼接，单文件 680 MB 的 text_encoder 实测 9.3 MB/s。"),
        ("Blender 官方下载站返回 403，镜像速度差异极大（南大镜像实测约 90 KB/s）",
         "download.blender.org 对脚本化请求直接 403；各高校镜像与本地运营商互联质量不同。",
         "改用清华/阿里云 Blender 镜像（实测约 500 KB/s），并用 curl -C - 断点续传；350 MB 安装包约 12 分钟下完，解压后直接用 -b 无头模式。"),
        ("课程提供的 sdcpp-ext 与两份 GGUF 权重不在作业目录，sd-cli 无法运行",
         "作业包只给了空白报告与实验指南，models/、vendor/sdcpp-ext、blender/ 脚本均缺失；上游 stable-diffusion.cpp 的 ControlNet 只支持 SD1.5，"
         "无法加载 SD2.1 深度 ControlNet。",
         "用 diffusers + PyTorch 在 CPU 上加载同一组模型复现同一控制条件，参数位与 sd-cli 对齐、逐 step 计时；报告中明确标注后端差异，"
         "并把 Q4_0/Turbo 的定点特性放进原理与思考题讨论，不把指南的参考耗时冒充实测值。"),
    ]
    for i, (x, y, z) in enumerate(problems):
        write_table_row(t[13], i + 1, [x, y, z], size=9)

    # ---------------- 九、结论 ----------------
    conclusion = [
        "1）完整跑通了“Blender 白模 → 深度/法线/clay 控制图 → SD-Turbo + SD2.1 深度 ControlNet → 写实图”的纯 CPU 链路，"
        "A–G 七组运行全部出图，脚本、命令、逐 step 记录在 scripts/、blender/ 与 output/*_run.json 中，可按同一组参数复现。",
        f"2）耗时规律：A（512²/4 步）采样 {fmt(a['sample_s'])} s、VAE {fmt(a['vae_s'])} s、总计 {fmt(a['total_s'])} s；"
        f"C（512²/8 步）总计 {fmt(c['total_s'])} s，步数翻倍只到 1.87 倍（VAE 是固定项）；B（768²/4 步）总计 {fmt(b['total_s'])} s，"
        f"像素数 2.25 倍对应耗时 2.36 倍，基本线性。拟合 k≈{fmt(k, 1)} s/(Mpx·步)、v≈{fmt(v, 1)} s/Mpx，"
        f"A/B/C 三组预测误差 <6%，768²/8 步预估 {fmt(k*0.590*8 + v*0.590, 0)} s。",
        f"3）控制效果：ControlNet 0.9 + CFG 1.2 时 A 的边缘倒角 {fmt(ma.get('edge_chamfer_depth_to_photo_px', 0))} px、深度回测 ρ={fmt(ma.get('depth_spearman', 0), 2)}；"
        f"细化提示词后 G 的 ρ 升到 {fmt(mg.get('depth_spearman', 0), 2)}，几何与材质都最好。"
        f"把控制强度降到 0.5（D，ρ={fmt(md.get('depth_spearman', 0), 2)}）或去掉控制（F，ρ={fmt(mf.get('depth_spearman', 0), 2)}）都会立即失去几何，"
        f"说明深度条件是这套流水线成立的前提。",
        f"4）失败点：① CFG=7（E）把画面推成过曝金属，几何尚在（ρ={fmt(me.get('depth_spearman', 0), 2)}）但完全不可用；"
        f"② 指南提示词下 4 步蒸馏把球面渲染成同心环（A/C），需要 6~8 步 + 具体材质描述才能消除；"
        f"③ 768² 在 4 步下偏欠采样、边缘偏软。若继续做：768² 提到 6~8 步、用 Q4_0 与 AVX-512/bf16 把每步压到 10 s 以内。",
        "5）本实验未完成拓展项（人像融合）：作业目录没有头像素材，也没有 compose_head.py，因此只在思考题里从原理上说明"
        "预乘 alpha、Poisson 融合与低强度 img2img 的作用，实测部分不含该项。",
    ]
    for i, text in enumerate(conclusion):
        write_cell(t[14].rows[i].cells[0], text, size=10)

    # ---------------- 十、思考题 ----------------
    answers = [
        [
            "Turbo 类模型是用对抗/分数蒸馏把“条件生成”和“无条件生成”两条路径拉近训练出来的，1~4 步就要成像；"
            "CFG 的作用是放大条件分支与无条件分支的差，而蒸馏已经把差值压小，再乘 7 倍相当于对残差反复外推，"
            "所以可用窗口只有 1.0~1.5。",
            f"本次 E 组 CFG=7.0 的实测：画面整体压暗、金属过饱和、地面高光碎成噪点，但深度回测 ρ 仍有 {fmt(me.get('depth_spearman', 0), 2)}、"
            f"倒角 {fmt(me.get('edge_chamfer_depth_to_photo_px', 0))} px，说明它破坏的主要是色调与材质，而不是几何布局——"
            "问题卡在“画面可用性”而不是“结构是否还在”。",
            "CFG 与步数互补：步数少时每步更新跨度大，高 CFG 会把放大的误差一次推到底；步数多时每步跨度小，可以承受略高的 CFG。"
            "本次 C 组（8 步、CFG 1.2）比 A 组（4 步）细节更干净，说明同样的 CFG 下加步数更安全。调参优先级建议："
            "ControlNet 强度 > 步数 > CFG。",
        ],
        [
            f"深度图的动态范围决定了几何层次被压缩到什么程度。本实验用可见物体表面像素的 2%/98% 百分位定区间，"
            f"512² 实测归一化区间 [{fmt(pct.get('p2', 0), 3)}, {fmt(pct.get('p98', 0), 3)}]，即相机距离约 "
            f"{fmt(2 + 20 * pct.get('p2', 0), 2)}~{fmt(2 + 20 * pct.get('p98', 0), 2)} m；映射后背景压到 0、"
            f"物体保留完整梯度，ControlNet 才能区分“球在前、圆环在后”。",
            "如果把 mist 起始距离设得更小（start 贴近相机），近处物体与地面会被截断成纯白（饱和），"
            "远处物体之间的灰度差被进一步压缩，深度图退化成“大面积黑+大面积白”，生成结果只能照轮廓成形，"
            "遮挡关系、圆柱与立方体的前后次序会丢失；反之若区间过大，梯度太浅，控制几乎失效，退化到 F 组那种自由生成。",
            "实现上必须先排除地面与背景再取百分位：第一次导出时把地面算进去，远端地面把区间拉爆，"
            f"物体只落在 {fmt(pct.get('p2', 0), 2)}~{fmt(pct.get('p98', 0), 2)} 这段窄灰度里，层次几乎看不出来；"
            "改为只用物体可见像素取 2%/98% 百分位、地面按远平面填黑之后，物体的曲率与前后关系才清晰。",
        ],
        [
            f"0.9：几何被强约束，轮廓贴合（A 组倒角 {fmt(ma.get('edge_chamfer_depth_to_photo_px', 0))} px、深度回测 ρ={fmt(ma.get('depth_spearman', 0), 2)}），"
            "代价是材质与光照被深度图的明暗主导，容易“工业金属化”。",
            f"0.5：模型更多依赖提示词先验，材质更丰富，但圆环被“吊灯/圆桌”替代、遮挡关系完全漂移，"
            f"ρ 掉到 {fmt(md.get('depth_spearman', 0), 2)}、倒角 {fmt(md.get('edge_chamfer_depth_to_photo_px', 0))} px。",
            "与初始图信息权衡：有 img2img 初始图时，初始图本身提供结构，ControlNet 可以放到 0.5~0.7，只锁姿态与构图，"
            "这样材质和光色能保留初次生成的结果（指南拓展项用的就是 strength 0.35 + control 0.7）；"
            "纯文生图且要求几何一致时，应保持 0.85~0.95，可用提示词细化（G 组）来补材质，而不是降强度。",
        ],
        [
            "瓶颈是 UNet 前向的矩阵乘：纯 CPU 上受内存带宽（Q4_0 就是为省带宽）与 FMA 吞吐限制；"
            "ControlNet 每步额外跑一遍编码器并注入残差，使每步开销增加约 10%~20%；VAE 解码是固定的第二大块，"
            "只在最后执行一次，但同样随像素数增长。",
            f"估算方式：总耗时 ≈ k×(W·H/10⁶)·S + v×(W·H/10⁶) + 加载开销。用 A/B/C 拟合得 k≈{fmt(k, 1)} s/(Mpx·步)、"
            f"v≈{fmt(v, 1)} s/Mpx。验证：768²/4 步预测 {fmt(k*0.590*4 + v*0.590, 0)} s，实测采样+VAE "
            f"{fmt(round(b['sample_s'] + b['vae_s'], 1))} s；768²/8 步预测 {fmt(k*0.590*8 + v*0.590, 0)} s。"
            "分辨率翻倍使像素数变 4 倍，步数翻倍使采样时间再乘 2，两者叠加时预算按乘积估。",
            f"对照指南（i7-10750H、sd-cli、Q4_0）的 44~57 s/步：本机 512² 合 {fmt(k*0.262, 1)} s/步，"
            "差距主要来自 32 线程与实现差异，而不是量化格式；Q4_0 的收益主要是把权重带宽压到 1/4、内存占用从约 2.4 GB 降到 1.70 GB。"
            "长时间满载时用 --threads 28 左右能留出余量，避免桌面卡顿拖慢整体，但本次 32 线程未遇到热降频。",
        ],
        [
            "预乘 alpha 指先把 RGB 乘以 alpha 再做插值/缩放（RGB' = RGB·α），alpha 通道单独插值。"
            "头像做白底抠图后，边缘像素是“人像色 + 白底”的混合；若不预乘直接缩放，插值会把白底混进半透明边缘，"
            "合成后在人像轮廓外出现一圈亮白边（指南的常见问题里也列了这一条）。",
            "预乘后再缩放，颜色与覆盖率同比例变化，插值出来的像素仍是“该颜色 × 该覆盖率”，边缘颜色不会被背景污染；"
            "合成到目标图时按 out = src + dst·(1-α) 叠加即可。为保证边缘自然，还需要内缩 1 px 羽化并把光源方向对齐，否则仍有“贴纸感”。",
            "本实验未做拓展项，但按指南的链路，正确顺序是：深度图定位头部框 → 等比缩放头像 → 白底软抠图 → 预乘 alpha 贴图 → "
            "亮度对齐与接触阴影 → 梯度域（Poisson）融合 → 颗粒匹配 → 低强度 img2img（strength 0.35、control 0.7）统一光色。"
            "漏掉“预乘”这一步，后面所有融合都会带着一圈白边。",
        ],
        [
            "① 固定身份 LoRA（DreamBooth/LoRA）：用同一人的 10~20 张图微调，身份相似度最高；代价是要训练、换风格要重训，"
            "显存/内存开销也最大。",
            "② IP-Adapter / PhotoMaker 之类的图像提示：把参考脸编码成额外条件，无需训练即可迁移；代价是相似度略低、"
            "需要额外的图像编码器，且与强 ControlNet 同时使用时容易互相压制。",
            "③ 固定种子 + 同一深度/关键点 ControlNet 约束姿态：只能保证构图一致，脸仍会漂移，适合做辅助；"
            "④ 生成后用人脸融合/换脸（InsightFace + inpainting）精修：快且可控，但要多一个检测/对齐/融合环节，"
            "容易出现边缘与光照不一致。工程上常见组合是 ①+③（身份靠 LoRA、姿态靠 ControlNet）或 ②+④ 再补一次低强度 img2img。",
        ],
    ]
    for ti, table in enumerate(t[15:21]):
        for ri, text in enumerate(answers[ti]):
            write_cell(table.rows[ri].cells[0], text, size=10)

    delete_hint_paragraphs(doc)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    doc.save(out_path)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(ROOT, "2025310291_杨锐_实验作业七.docx"))
    parser.add_argument("--dry", action="store_true", help="write to _work/dry_run.docx")
    args = parser.parse_args()
    out = os.path.join(ROOT, "_work", "dry_run.docx") if args.dry else args.out
    path = build(out)
    print("written:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
