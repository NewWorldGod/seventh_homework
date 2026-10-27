# -*- coding: utf-8 -*-
"""One-shot pipeline: Blender control maps -> CPU depth-ControlNet generation.

The command-line parameters mirror the experiment guide so the runs stay
comparable (resolution / steps / CFG / ControlNet strength / seed / threads).

Backend note: the course build `sdcpp-ext` (stable-diffusion.cpp with SD2.1
ControlNet support) and its GGUF weights are not shipped in this workspace, so
the same models (SD-Turbo + SD2.1 depth ControlNet) are executed through
diffusers/PyTorch on the CPU.  Sampling and VAE decoding are timed separately,
exactly like the sampling/VAE split reported for sd-cli.

Example:
    python scripts/run_pipeline.py --name a512 --res 512 --steps 4 --cfg 1.2
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SD_DIR = os.path.join(ROOT, "models", "hf", "sd-turbo")
CN_DIR = os.path.join(ROOT, "models", "hf", "controlnet-sd21-depth")
BLENDER = os.environ.get(
    "BLENDER_EXE", os.path.join(ROOT, "tools", "blender-4.5.13-windows-x64", "blender.exe")
)
PROMPT = (
    "photorealistic render, studio soft lighting, PBR material, "
    "preserve original 3d geometry, sharp"
)
NEGATIVE = "deformed geometry, perspective changed"


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def peak_rss_mb() -> float:
    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    handle = kernel32.GetCurrentProcess()
    fn = kernel32.K32GetProcessMemoryInfo
    fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
    fn.restype = wintypes.BOOL
    fn(handle, ctypes.byref(counters), counters.cb)
    return counters.PeakWorkingSetSize / (1024 * 1024)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--name", default="test512")
    p.add_argument("--res", type=int, default=512)
    p.add_argument("--steps", type=int, default=4)
    p.add_argument("--cfg", type=float, default=1.2)
    p.add_argument("--control-strength", type=float, default=0.9)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--threads", type=int, default=-1)
    p.add_argument("--control-image", default=None)
    p.add_argument("--prompt", default=PROMPT)
    p.add_argument("--negative-prompt", default=NEGATIVE)
    p.add_argument("--dtype", default="fp32", choices=["fp32", "bf16"])
    p.add_argument("--outdir", default=os.path.join(ROOT, "output"))
    return p.parse_args()


def ensure_control_image(args: argparse.Namespace) -> str:
    if args.control_image:
        return os.path.abspath(args.control_image)
    candidates = [
        os.path.join(args.outdir, f"{args.name}_depth_0001.png"),
        os.path.join(args.outdir, "demo_depth_0001.png" if args.res == 512 else f"demo{args.res}_depth_0001.png"),
        os.path.join(args.outdir, "demo_depth_0001.png"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    blend = os.path.join(ROOT, "assets", "demo_white_model.blend")
    script = os.path.join(ROOT, "blender", "export_control_maps.py")
    print(f"[pipeline] control map missing, running Blender export for {args.name}", flush=True)
    cmd = [
        BLENDER, "-b", blend, "-P", script, "--",
        "--outdir", args.outdir, "--name", args.name, "--res", str(args.res),
    ]
    subprocess.run(cmd, check=True)
    return candidates[0]


def main() -> int:
    args = parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    os.environ.setdefault("HF_HUB_OFFLINE", "1")

    control_path = ensure_control_image(args)

    import torch
    from diffusers import ControlNetModel, StableDiffusionControlNetPipeline
    from PIL import Image

    torch.set_grad_enabled(False)
    threads = args.threads if args.threads > 0 else os.cpu_count()
    torch.set_num_threads(threads)
    dtype = torch.float32 if args.dtype == "fp32" else torch.bfloat16

    t_load = time.time()
    controlnet = ControlNetModel.from_pretrained(CN_DIR, torch_dtype=dtype, use_safetensors=False)
    pipe = StableDiffusionControlNetPipeline.from_pretrained(
        SD_DIR,
        controlnet=controlnet,
        torch_dtype=dtype,
        variant="fp16",
        safety_checker=None,
        feature_extractor=None,
        requires_safety_checker=False,
        local_files_only=True,
    )
    pipe.to("cpu")
    pipe.set_progress_bar_config(disable=False)
    load_s = time.time() - t_load

    control = Image.open(control_path).convert("RGB").resize((args.res, args.res), Image.BICUBIC)
    generator = torch.Generator("cpu").manual_seed(args.seed)

    step_times: list[float] = []
    last = [time.time()]

    def on_step_end(pipeline, step_index, timestep, callback_kwargs):
        now = time.time()
        step_times.append(now - last[0])
        last[0] = now
        return callback_kwargs

    common = dict(
        prompt=args.prompt,
        negative_prompt=args.negative_prompt,
        num_inference_steps=args.steps,
        guidance_scale=args.cfg,
        image=control,
        controlnet_conditioning_scale=args.control_strength,
        width=args.res,
        height=args.res,
        generator=generator,
        output_type="latent",
        callback_on_step_end=on_step_end,
    )

    t_sample = time.time()
    last[0] = t_sample
    latents = pipe(**common).images
    sample_s = time.time() - t_sample

    t_vae = time.time()
    scaled = latents / pipe.vae.config.scaling_factor
    decoded = pipe.vae.decode(scaled, return_dict=False)[0]
    image = (decoded / 2 + 0.5).clamp(0, 1).float()
    vae_s = time.time() - t_vae
    total_s = time.time() - t_sample

    arr = (image[0].permute(1, 2, 0).cpu().numpy() * 255.0 + 0.5).astype("uint8")
    out_png = os.path.join(args.outdir, f"{args.name}_photoreal.png")
    Image.fromarray(arr).save(out_png)

    run = {
        "name": args.name,
        "res": args.res,
        "steps": args.steps,
        "cfg": args.cfg,
        "control_strength": args.control_strength,
        "seed": args.seed,
        "threads": threads,
        "dtype": args.dtype,
        "scheduler": type(pipe.scheduler).__name__,
        "backend": "diffusers %s / PyTorch %s / CPU" % (__import__("diffusers").__version__, torch.__version__),
        "control_image": os.path.basename(control_path),
        "load_s": load_s,
        "step_times_s": step_times,
        "per_step_s": sum(step_times) / len(step_times) if step_times else None,
        "sample_s": sample_s,
        "vae_s": vae_s,
        "total_s": total_s,
        "peak_rss_mb": peak_rss_mb(),
        "output": os.path.basename(out_png),
    }
    run_path = os.path.join(args.outdir, f"{args.name}_run.json")
    with open(run_path, "w", encoding="utf-8") as fh:
        json.dump(run, fh, indent=2, ensure_ascii=False)
    print("RUN_SUMMARY " + json.dumps(run, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
