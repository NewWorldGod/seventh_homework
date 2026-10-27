# -*- coding: utf-8 -*-
"""Geometric-consistency metrics for the depth-control runs.

Primary metric -- depth round-trip agreement:
    A monocular depth estimator (Depth-Anything V2 Small, 24.8M params, CPU)
    predicts relative depth for the generated image; its Spearman rank
    correlation with the control depth map over the object region measures how
    much of the original geometry survived.  Rank correlation is used because
    monocular depth has an unknown scale and offset.

Secondary metric -- edge chamfer distance (px) between depth-map edges and
generated-image edges, in both directions.

Run F (control strength 0) is the "no control" reference: its numbers show what
the metric looks like when the depth map is ignored.
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.stats import spearmanr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output")
DEPTH_MODEL = os.path.join(ROOT, "models", "hf", "depth-anything-v2-small")


def load_gray(path: str) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.float32) / 255.0


def edges(gray: np.ndarray, percentile: float) -> np.ndarray:
    gy, gx = np.gradient(ndimage.gaussian_filter(gray, 1.0))
    mag = np.hypot(gx, gy)
    thr = np.percentile(mag, percentile)
    return mag > max(thr, 1e-4)


def resize_to(arr: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    if arr.shape == shape:
        return arr
    img = Image.fromarray(arr.astype(np.float32))
    return np.asarray(img.resize(shape[::-1], Image.BICUBIC), dtype=np.float32)


def main() -> int:
    import torch
    from transformers import pipeline

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    torch.set_grad_enabled(False)
    estimator = pipeline("depth-estimation", model=DEPTH_MODEL, device="cpu")

    alpha_cache: dict[int, np.ndarray] = {}

    def alpha_for(res: int) -> np.ndarray:
        if res not in alpha_cache:
            path = os.path.join(OUT, "demo_alpha.png" if res == 512 else f"demo{res}_alpha.png")
            alpha_cache[res] = (
                np.asarray(Image.open(path).convert("L"), dtype=np.float32) / 255.0 > 0.5
            )
        return alpha_cache[res]

    runs = []
    for run_json in sorted(glob.glob(os.path.join(OUT, "*_run.json"))):
        with open(run_json, encoding="utf-8") as fh:
            run = json.load(fh)
        name = run["name"]
        photo_path = os.path.join(OUT, f"{name}_photoreal.png")
        if not os.path.exists(photo_path):
            continue
        depth_path = os.path.join(OUT, run.get("control_image") or "demo_depth_0001.png")
        control = load_gray(depth_path)
        alpha = alpha_for(run["res"])
        target_shape = alpha.shape
        control = resize_to(control, target_shape)

        pred = estimator(Image.open(photo_path).convert("RGB"))["predicted_depth"]
        pred = pred.squeeze().numpy().astype(np.float32)
        pred = resize_to(pred, target_shape)

        mask = ndimage.binary_dilation(alpha, iterations=3)
        rho = float(spearmanr(control[mask], pred[mask]).statistic)

        d_edges = edges(np.clip(1.0 - control, 0, 1), 92.0) & mask
        photo_gray = np.asarray(Image.open(photo_path).convert("L"), dtype=np.float32) / 255.0
        photo_gray = resize_to(photo_gray, target_shape)
        i_edges = edges(ndimage.gaussian_filter(photo_gray, 1.0), 92.0)
        dist_to_img = ndimage.distance_transform_edt(~i_edges)
        dist_to_dep = ndimage.distance_transform_edt(~d_edges)
        chamfer_forward = float(dist_to_img[d_edges].mean()) if d_edges.any() else float("nan")
        chamfer_backward = float(dist_to_dep[i_edges].mean()) if i_edges.any() else float("nan")

        runs.append(
            {
                "name": name,
                "res": run["res"],
                "steps": run["steps"],
                "cfg": run["cfg"],
                "control_strength": run["control_strength"],
                "depth_spearman": round(rho, 4),
                "edge_chamfer_depth_to_photo_px": round(chamfer_forward, 3),
                "edge_chamfer_photo_to_depth_px": round(chamfer_backward, 3),
                "sample_s": run["sample_s"],
                "vae_s": run["vae_s"],
                "total_s": run["total_s"],
                "peak_rss_mb": round(run["peak_rss_mb"], 1),
            }
        )
        print(f"[metric] {name}: rho={rho:.3f} chamfer={chamfer_forward:.2f}/{chamfer_backward:.2f} px", flush=True)

    payload = {"alpha_coverage": float(alpha_for(512).mean()), "runs": runs}
    with open(os.path.join(OUT, "metrics.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    print(json.dumps(payload["runs"], indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
