# seventh_homework · 白膜转写实：纯 CPU 深度控制生成流水线

《大模型通识》作业七代码与实验数据。整条链路是：**Blender 白模 → 深度/法线/clay 控制图 → 深度 ControlNet + SD-Turbo 少步数采样（纯 CPU）→ 写实化结果 → 几何一致性量化评估**。

- 姓名 / 学号：杨锐 / 2025310291
- 实验日期：2026-10-27
- 运行环境：AMD Ryzen 9 8945HX（16 核 32 线程）、31.3 GB 内存、Windows 11、Blender 4.5.13 LTS、Python 3.14、PyTorch 2.14.0（CPU）、diffusers 0.42.1

## 目录结构

```
blender/
  make_demo_scene.py       生成白模场景（球/圆环/倒角立方体/圆柱+地面+三点光+63mm 相机）
  export_control_maps.py   无头导出 depth(Mist 2%/98% 百分位反相)/normal/clay/alpha
scripts/
  run_pipeline.py          纯 CPU 推理流水线，参数位与 sd-cli 对齐，逐 step/VAE 计时 + 峰值内存
  analyze_geometry.py      深度回测 ρ（Depth-Anything-V2-Small）+ 边缘倒角距离
  compose_figures.py       合成报告插图（控制图三联、A/B 对比、消融、提示词对比）
  build_report.py          把 output/ 的实测数据填进空白模板生成报告
assets/
  demo_white_model.blend   白模场景文件
logs/                      Blender 导出 JSON + 7 组运行的完整日志
output/                    四类控制图、七组 photoreal 结果、run json、metrics.json、报告插图
2025310291_杨锐_实验作业七.docx / .pdf   实验报告
```

## 权重与依赖（不随仓库分发）

模型与二进制体积太大，仓库里不含：

| 组件 | 说明 | 存放位置（脚本默认） |
|---|---|---|
| SD-Turbo | stabilityai/sd-turbo，fp16 变体（UNet 1.65 GB + VAE 0.16 GB + 文本编码器 0.65 GB） | `models/hf/sd-turbo/` |
| 深度 ControlNet | thibaud/controlnet-sd21-depth-diffusers（695 MB，SD2.1，364.2M 参数） | `models/hf/controlnet-sd21-depth/` |
| 深度回测模型 | depth-anything/Depth-Anything-V2-Small-hf（99 MB） | `models/hf/depth-anything-v2-small/` |
| Blender | 4.5.13 LTS windows-x64，`-b` 无头模式 | `tools/blender-4.5.13-windows-x64/blender.exe`（可用环境变量 `BLENDER_EXE` 覆盖） |

Python 依赖见 `requirements.txt`。

## 复现步骤

```bash
# 1) 生成白模场景
blender -b -P blender/make_demo_scene.py -- --out assets/demo_white_model.blend --res 512

# 2) 导出 512² 控制图（clay / depth / normal / alpha）
blender -b assets/demo_white_model.blend -P blender/export_control_maps.py -- \
    --outdir output --name demo --res 512 --samples 64

# 3) 主结果：512² / 4 步 / CFG 1.2 / ControlNet 0.9 / seed 42
python scripts/run_pipeline.py --name a512 --res 512 --steps 4 --cfg 1.2 \
    --control-strength 0.9 --seed 42

# 4) 768² 控制图 + 768²/4 步
blender -b assets/demo_white_model.blend -P blender/export_control_maps.py -- \
    --outdir output --name demo768 --res 768 --samples 64
python scripts/run_pipeline.py --name b768 --res 768 --steps 4 --cfg 1.2 --control-strength 0.9

# 5) 参数对照（步数 / ControlNet 强度 / CFG / 无控制）+ 提示词细化
python scripts/run_pipeline.py --name c512s8  --steps 8
python scripts/run_pipeline.py --name d_cn05  --control-strength 0.5
python scripts/run_pipeline.py --name e_cfg7  --cfg 7.0
python scripts/run_pipeline.py --name f_cn00  --control-strength 0.0

# 6) 量化评估 + 报告插图
python scripts/analyze_geometry.py
python scripts/compose_figures.py
```

## 后端说明（重要）

作业包应提供的 `vendor/sdcpp-ext`（支持 SD2.1 深度 ControlNet 的 stable-diffusion.cpp 扩展版）与两份 GGUF 权重未随作业目录提供，而上游 stable-diffusion.cpp 的 ControlNet 只支持 SD1.5，无法加载 SD2.1 深度 ControlNet。

因此本仓库用 **diffusers + PyTorch 在 CPU 上加载同一组模型**（SD-Turbo SD2.1 + SD2.1 深度 ControlNet），命令行参数（`--res/--steps/--cfg/--control-strength/--seed/--threads`）与 sd-cli 一一对应，并把采样与 VAE 解码分开计时。报告中所有耗时均为该实现的实测值，指南的 i7-10750H + Q4_0 数据只作对照并已明确标注，没有冒充实测。

## 实测结果概览

| 运行 | 分辨率 | 步数 | CFG | ControlNet | 采样(s) | VAE(s) | 总计(s) | 深度回测 ρ |
|---|---|---|---|---|---|---|---|---|
| A | 512² | 4 | 1.2 | 0.9 | 20.8 | 4.6 | 25.4 | 0.28 |
| B | 768² | 4 | 1.2 | 0.9 | 49.7 | 10.2 | 59.9 | 0.59 |
| C | 512² | 8 | 1.2 | 0.9 | 43.6 | 4.0 | 47.6 | 0.49 |
| D | 512² | 4 | 1.2 | 0.5 | 17.3 | 4.3 | 21.6 | -0.07 |
| E | 512² | 4 | 7.0 | 0.9 | 17.5 | 4.0 | 21.5 | 0.83 |
| F | 512² | 4 | 1.2 | 0.0 | 21.8 | 5.3 | 27.1 | -0.09 |
| G | 512² | 6 | 1.2 | 0.9 | 31.8 | 4.9 | 36.7 | 0.87 |

拟合耗时模型：采样 ≈ **20.8 s/(Mpx·步)**，VAE ≈ **17.1 s/Mpx**（A/B/C 三组预测误差 < 6%）。峰值进程内存：A 组 8.2 GB、B 组 9.7 GB。

结论要点：ControlNet 0.9 是几何保持的必要条件（降到 0.5 就漂移、去掉控制完全自由生成）；CFG=7 主要破坏色调与材质（过曝），几何布局仍在；提示词决定材质、深度控制决定几何，细化提示词后 ρ 从 0.28 升到 0.87。
