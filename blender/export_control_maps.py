# -*- coding: utf-8 -*-
"""Export depth / normal / clay control maps from the white-model scene.

Run headless:
    blender -b assets/demo_white_model.blend -P blender/export_control_maps.py -- \
        --outdir output --name demo --res 512 --samples 64

Outputs (same naming as the experiment guide):
    <outdir>/<name>_depth_0001.png    inverted depth: near = bright
    <outdir>/<name>_normal_0001.png   world normal mapped with n*0.5+0.5
    <outdir>/<name>_clay.png          matte-white reference render
    <outdir>/<name>_alpha.png         object coverage mask (for later metrics)

Depth comes from the Cycles Mist pass, which is composited into a 32-bit EXR
so the percentile stretch is computed on real linear values instead of an
already tone-mapped 8-bit image.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time
import zlib

import bpy
import numpy as np

CAMERA_Z_START = 2.0
CAMERA_Z_DEPTH = 20.0


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--outdir", default="output")
    p.add_argument("--name", default="demo")
    p.add_argument("--res", type=int, default=512)
    p.add_argument("--samples", type=int, default=64)
    p.add_argument("--percentiles", default="2,98")
    return p.parse_args(argv)


def write_png(path: str, arr: np.ndarray) -> None:
    """Minimal PNG encoder (RGB8 / RGBA8) so Blender does not need PIL."""
    h, w, c = arr.shape
    color_type = 2 if c == 3 else 6
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw.extend(arr[y].tobytes())

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    payload = b"\x89PNG\r\n\x1a\n"
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, color_type, 0, 0, 0))
    payload += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    payload += chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(payload)


def load_pass_pixels(path: str) -> np.ndarray:
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    buf = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    bpy.data.images.remove(img)
    return buf.reshape(h, w, 4)[::-1]  # Blender images are bottom-up


def setup_compositor(scene: bpy.types.Scene, pass_name: str) -> None:
    """Route one render pass (Mist or Normal) straight into the Composite node."""
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    rl = tree.nodes.new("CompositorNodeRLayers")
    comp = tree.nodes.new("CompositorNodeComposite")
    if pass_name == "Mist":
        combine = tree.nodes.new("CompositorNodeCombineColor")
        combine.mode = "RGB"
        for idx in (0, 1, 2):
            combine.inputs[idx].default_value = 0.0
        tree.links.new(rl.outputs["Mist"], combine.inputs[0])
        tree.links.new(rl.outputs["Mist"], combine.inputs[1])
        tree.links.new(rl.outputs["Mist"], combine.inputs[2])
        tree.links.new(combine.outputs["Image"], comp.inputs["Image"])
    else:
        tree.links.new(rl.outputs["Normal"], comp.inputs["Image"])


def render_to(scene: bpy.types.Scene, path: str, fmt: str = "PNG") -> float:
    scene.render.filepath = path
    scene.render.image_settings.file_format = fmt
    if fmt == "OPEN_EXR":
        scene.render.image_settings.color_depth = "32"
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    return time.time() - t0


def main() -> int:
    args = parse_args()
    scene = bpy.context.scene
    outdir = os.path.abspath(args.outdir)
    os.makedirs(outdir, exist_ok=True)
    tmpdir = os.path.join(outdir, "_tmp")
    os.makedirs(tmpdir, exist_ok=True)

    scene.render.resolution_x = args.res
    scene.render.resolution_y = args.res
    scene.render.resolution_percentage = 100
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.use_denoising = True
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"

    # Mist pass: linear camera distance, used as the source of the depth map
    scene.world.mist_settings.start = CAMERA_Z_START
    scene.world.mist_settings.depth = CAMERA_Z_DEPTH
    view_layer = bpy.context.view_layer
    view_layer.use_pass_mist = True
    view_layer.use_pass_normal = True

    timings: dict[str, float] = {}

    # 1) Mist -> EXR (no noise, 1 sample is enough)
    scene.cycles.samples = 1
    scene.render.film_transparent = False
    scene.render.image_settings.color_mode = "RGB"
    setup_compositor(scene, "Mist")
    timings["depth"] = render_to(scene, os.path.join(tmpdir, "mist.exr"), "OPEN_EXR")

    # 2) Normal -> EXR
    setup_compositor(scene, "Normal")
    timings["normal"] = render_to(scene, os.path.join(tmpdir, "normal.exr"), "OPEN_EXR")

    # 3) Clay reference render (opaque studio background) + alpha mask pass
    scene.use_nodes = False
    scene.render.film_transparent = False
    scene.render.image_settings.color_mode = "RGB"
    scene.cycles.samples = args.samples
    clay_path = os.path.join(outdir, f"{args.name}_clay.png")
    timings["clay"] = render_to(scene, clay_path, "PNG")

    scene.render.film_transparent = True
    scene.render.image_settings.color_mode = "RGBA"
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    ground = bpy.data.objects.get("ground")
    if ground is not None:
        ground.hide_render = True  # the mask must contain the objects only
    alpha_path = os.path.join(tmpdir, "alpha.png")
    timings["alpha"] = render_to(scene, alpha_path, "PNG")
    if ground is not None:
        ground.hide_render = False

    # ---- post-process: percentiles, inversion, colour mapping ----
    mist = load_pass_pixels(os.path.join(tmpdir, "mist.exr"))[:, :, 0]
    normal = load_pass_pixels(os.path.join(tmpdir, "normal.exr"))[:, :, :3]
    alpha = load_pass_pixels(alpha_path)[:, :, 3]

    mask = alpha > 0.02
    # The percentile range is taken over the visible object surfaces, not over
    # the ground plane: the ground is a flat gradient that would otherwise
    # squeeze the objects into a few grey levels (the guide's "mist range blown
    # up by the distant floor" failure).  Ground pixels still keep their depth,
    # clipped by the same range.
    values = mist[mask]
    p_lo, p_hi = (float(v) for v in np.percentile(values, [float(x) for x in args.percentiles.split(",")]))
    norm = np.clip((mist - p_lo) / max(p_hi - p_lo, 1e-6), 0.0, 1.0)
    depth_image = 1.0 - norm  # near bright, far dark
    depth_image[~mask] = 0.0  # floor/world carry no geometry cue, keep them far

    depth8 = np.repeat((depth_image * 255.0 + 0.5).astype(np.uint8)[:, :, None], 3, axis=2)
    write_png(os.path.join(outdir, f"{args.name}_depth_0001.png"), depth8)

    normal_image = np.clip(normal * 0.5 + 0.5, 0.0, 1.0)
    normal_image[~mask] = 0.5
    normal8 = (normal_image * 255.0 + 0.5).astype(np.uint8)
    write_png(os.path.join(outdir, f"{args.name}_normal_0001.png"), normal8)

    write_png(os.path.join(outdir, f"{args.name}_alpha.png"), np.repeat((mask * 255).astype(np.uint8)[:, :, None], 3, axis=2))

    summary = {
        "res": args.res,
        "samples": args.samples,
        "name": args.name,
        "depth_percentiles": {"p2": p_lo, "p98": p_hi, "raw_min": float(mist.min()), "raw_max": float(mist.max())},
        "mask_coverage": float(mask.mean()),
        "render_seconds": timings,
        "outputs": {
            "depth": f"{args.name}_depth_0001.png",
            "normal": f"{args.name}_normal_0001.png",
            "clay": f"{args.name}_clay.png",
            "alpha": f"{args.name}_alpha.png",
        },
    }
    log_path = os.path.join(os.path.dirname(outdir), "logs", f"export_{args.res}.json")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
    print("EXPORT_SUMMARY " + json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
