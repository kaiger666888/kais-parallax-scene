---
name: kais-parallax-scene
version: 0.4.0
description: "2.5D视差场景生成器。将即梦/SD超宽图通过Windows GPU自动分层，复用kais-blender-engine远程构建视差场景并渲染动态镜头视频。全流程单机Windows执行，无需跨机器传输。触发词：视差场景, parallax, 2.5D场景, 宽图分层, parallax scene, 视差动画, 景深分层, 场景分层, 即梦宽图, 超宽图分层, parallax animation, 视差生成"
---

# kais-parallax-scene — 2.5D 视差场景生成器

> 将即梦/SD超宽图（21:9 / 32:9）自动分层为前景/中景/背景，
> 通过 **kais-blender-engine** 在 Windows GPU 端完成视差场景构建和渲染。
>
> **全流程单机执行**：分层（MiDaS GPU）+ 渲染（Blender GPU），无需跨机器传输。

## 前置依赖

<!-- FREEDOM:low -->

- **kais-blender-engine** skill 已安装，Windows 端 Blender Agent Server 运行中
- **Windows 端 Python 依赖**（已安装）：
  - `torch` 2.7+ (CUDA)
  - `transformers` (MiDaS DPT-Large)
  - `scipy` + `Pillow`
- **Linux 端**仅需 `requests` + `pydantic`（调用 engine API）

## 管线位置

```
即梦/SD 超宽图 ──→ [kais-parallax-scene] ──→ 动态镜头视频
                         │
                    全在Windows端
                         │
              ┌──────────┴──────────┐
         MiDaS深度分层(GPU)    Blender视差渲染(GPU)
              │                      │
         分层PNG + layers.json   generate_parallax_script()
              │                 engine.run_async()
              └──────────┬──────────┘
                         │
                    .mp4 + .blend
```

**与 kais-blender-layout 的关系**：
- layout 负责"3D资产场景"（角色+家具+HDRI建模渲染）
- parallax-scene 负责"2D超宽图→2.5D动态"（AI绘图分层+视差动画）
- 两者共享 kais-blender-engine 的 Windows GPU 渲染能力

---

## 全流程（两步，全Windows端）

```
步骤一：GPU深度分层              步骤二：GPU视差渲染
─────────────────────────────────────────────────────────
超宽图.png → MiDaS(CUDA)  →     engine.run_async()
           前景/中景/背景PNG  →    generate_parallax_script()
           layers.json          Blender Eevee → MP4
```

---

## 步骤一：深度分层（Windows GPU）

通过 engine 的 `run_async()` 在 Windows 端执行 MiDaS 深度估计：

```python
import sys
sys.path.insert(0, "/path/to/kais-blender-engine/client")
from blender_client import BlenderAgentClient

cli = BlenderAgentClient("http://192.168.71.38:8080")

# 读取分层脚本并发送到Windows执行
with open("scripts/depth_segment_win.py") as f:
    segment_code = f.read()

cmd = f"""
import sys
sys.argv = ["depth_segment_win.py", "D:/path/to/wide.png", "-o", "D:/BlenderAgent/cache/parallax/scene1", "-l", "3"]
{segment_code}
"""

job_id = cli.run_async(cmd, timeout=300)
status = cli.poll_job(job_id, interval=10, max_wait=300)
# 输出: D:/BlenderAgent/cache/parallax/scene1/{foreground,midground,background}.png + layers.json
```

**输出**：
- `foreground.png` / `midground.png` / `background.png` — 分层透明PNG
- `depth_map.png` — 深度灰度图
- `layers.json` — 图层配置（Z深度 + 路径）

### 分层方案

| 方案 | 说明 | 适用场景 |
|------|------|----------|
| MiDaS自动（默认） | `Intel/dpt-large`，GPU推理 ~1s | 通用场景 |
| 4层精细 | `-l 4`，增加distant层 | 复杂景深 |
| 手动蒙版 | 修改脚本跳过AI | 分割不完美时 |

---

## 步骤二：视差渲染（Windows GPU）

读取 `layers.json`，通过 engine 的 `generate_parallax_script()` 渲染：

```python
import sys, json
sys.path.insert(0, "/path/to/kais-blender-engine/client")
from blender_client import BlenderAgentClient
from generators.parallax import ParallaxParams, LayerConfig, generate_parallax_script

cli = BlenderAgentClient("http://192.168.71.38:8080")

params = ParallaxParams(
    preset_name="scene_001",
    layers=[
        LayerConfig(name="foreground", image_path="D:/.../foreground.png", z_depth=-1.5),
        LayerConfig(name="midground",  image_path="D:/.../midground.png",  z_depth=0.0),
        LayerConfig(name="background", image_path="D:/.../background.png", z_depth=7.5),
    ],
    camera_preset="scroll_left",
    duration=6.0,
    resolution=(1080, 1920),
    output_format="video",
    output_dir="D:/BlenderAgent/cache/parallax",
)

script = generate_parallax_script(params)
job_id = cli.run_async(script, timeout=600)
status = cli.poll_job(job_id, interval=10, max_wait=600)
# 输出: .mp4 + .blend + 帧序列
```

### 摄像机预设

| 预设 | 运动 | 适用场景 |
|------|------|----------|
| `scroll_left` | 横向平移←→，缓入缓出 | 场景展示、交代环境 |
| `scroll_right` | 反向平移→← | 反向展示 |
| `push_in` | 缓慢推进 | 聚焦主体 |
| `dolly_zoom` | 推近+缩小焦距 | Vertigo效果 |
| `orbit` | 环绕旋转90° | 物体展示 |
| `static` | 静态 | 仅输出分层场景图 |

### ParallaxParams 字段

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `preset_name` | str | 必填 | 输出文件名前缀 |
| `layers` | List[LayerConfig] | 必填 | 图层列表 |
| `camera_preset` | str | `scroll_left` | 摄像机预设 |
| `camera_focal_length` | float | 35.0 | 焦距(mm) |
| `camera_distance` | float | 2.0 | 摄像机Y轴距离 |
| `duration` | float | 6.0 | 动画时长(秒) |
| `fps` | int | 24 | 帧率 |
| `move_range` | float | 3.0 | 平移范围(米) |
| `output_format` | str | `video` | video / frames / both |
| `resolution` | tuple | (1080,1920) | (宽, 高) |
| `engine` | str | `BLENDER_EEVEE` | 渲染引擎 |
| `output_dir` | str | `D:/.../parallax` | Windows端输出目录 |

---

## 一键编排

```bash
# 全流程（Linux端编排，Windows端执行）
python3 scripts/parallax_pipeline.py \
  --image-path "D:/path/to/wide.png" \
  --name scene_001 \
  --camera scroll_left \
  --duration 6.0 \
  --ratio 9:16
```

---

## 硬件需求

| 步骤 | 资源 | 我们的配置 |
|------|------|-----------|
| MiDaS分层 | GPU VRAM 2-3GB, ~1s/张 | RTX 4070 ✅ |
| Blender渲染 | GPU VRAM 1-2GB, ~3s/72帧 | RTX 4070 ✅ |
| 模型存储 | ~1.3GB磁盘 | D盘充足 ✅ |

## 技术限制

| 限制 | 缓解方案 |
|------|----------|
| 无法镜头穿过前景 | 限制摄像机Z轴移动 |
| 侧面视角穿帮 | 边缘延伸10%+模糊 |
| 动态元素（水、火） | 结合视频生成工具 |
| 分割不完美 | 手动提供蒙版 |

---

## 双模式自动选择

<!-- FREEDOM:low -->

合成引擎根据**深度图方差**自动选择最佳模式：

| 模式 | 条件 | 效果 | 适用场景 |
|------|------|------|----------|
| **视差偏移** | `depth_variance > 0.12` | 各层按深度不同偏移 | 风景、户外、有纵深感 |
| **Ken Burns** | `depth_variance ≤ 0.12` | 缓慢缩放+平移 | 室内、平坦、浅景深 |

### 视差模式参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--parallax-strength` | 200 | 前景最大偏移(px) |

### Ken Burns模式参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--kenburns-zoom` | 1.15 | 缩放倍率（1.0=不缩放） |
| `--kenburns-pan` | 100 | 平移范围(px) |

### 强制指定模式

```bash
# 强制视差
python parallax_composite.py --image-dir <dir> --mode parallax --output out.mp4
# 强制Ken Burns
python parallax_composite.py --image-dir <dir> --mode kenburns --output out.mp4
# 自动选择（默认）
python parallax_composite.py --image-dir <dir> --output out.mp4
```

---

## 文件结构

```
kais-parallax-scene/
├── SKILL.md                          # 本文件
├── scripts/
│   ├── depth_segment_win.py          # Windows端深度分层脚本（GPU）
│   ├── parallax_composite.py         # 双模式合成引擎（核心）
│   └── parallax_pipeline.py          # 全流程编排
└── references/
    ├── parallax-math.md              # 视差数学原理
    └── midas-setup.md                # MiDaS安装指南
```
