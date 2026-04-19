---
name: kais-parallax-scene
version: 0.2.0
description: "2.5D视差场景生成器。将即梦/SD超宽图自动分层，通过kais-blender-engine远程构建视差场景并渲染动态镜头视频。依赖kais-blender-engine的ParallaxParams generator和run_sync API。触发词：视差场景, parallax, 2.5D场景, 宽图分层, parallax scene, 视差动画, 景深分层, 场景分层, 即梦宽图, 超宽图分层, parallax animation, 视差生成"
---

# kais-parallax-scene — 2.5D 视差场景生成器

> 将即梦/SD超宽图（21:9 / 32:9）自动分层为前景/中景/背景，
> 通过 **kais-blender-engine** 的 `generate_parallax_script()` + `run_sync()` 构建视差场景并渲染。
>
> **核心价值**：一张静态超宽图 + AI分割 → 动态镜头视频，避免全3D建模的高成本。

## 前置依赖

<!-- FREEDOM:low -->

- **kais-blender-engine** skill 已安装，Windows 端 Blender Agent Server 运行中
- **Python 依赖**：`pip install requests numpy Pillow scipy transformers torch`
- **AI 分割模型**（Linux 端执行）：
  - 推荐：`transformers` pipeline（MiDaS DPT-Large，首次自动下载 ~1.3GB）
  - 备选：支持用户手动提供蒙版（PS绘制黑白图）

## 管线位置

```
即梦/SD 超宽图 ──→ [kais-parallax-scene] ──→ 动态镜头视频
     │                       │
     │              ┌────────┴────────┐
     │         Linux端(分层)    Windows端(渲染)
     │         depth_segment    kais-blender-engine
     │              │               │
     │         分层PNG+JSON   generate_parallax_script()
     │              │         run_sync()
     └──────────────┴───────────────┘
```

**与 kais-blender-layout 的关系**：
- layout 负责"3D资产场景"（角色+家具+HDRI建模渲染）
- parallax-scene 负责"2D超宽图→2.5D动态"（AI绘图分层+视差动画）
- 两者共享 kais-blender-engine 的渲染能力（同一个 server，同一个 client）

---

## 全流程（两阶段）

```
阶段一：Linux端 — 智能分层          阶段二：Windows端 — 视差渲染
────────────────────────────────────────────────────────────────────
超宽图.png → MiDaS深度估计 →  engine client → Blender场景构建 → 视频输出
           → 前景/中景/背景PNG  generate_parallax_script()
           → layers.json        run_sync()
```

---

## 阶段一：智能分层（Linux端）

<!-- FREEDOM:low -->

使用 MiDaS 单目深度估计模型，零人工干预：

```bash
# 基本用法
python3 scripts/depth_segment.py wide_image.png -o ./segments -l 3

# 使用手动蒙版（跳过AI）
python3 scripts/depth_segment.py wide_image.png --manual-mask mask.png

# 4层精细分割
python3 scripts/depth_segment.py wide_image.png -l 4
```

**输出**：
- `segments/foreground.png` — 前景（透明背景）
- `segments/midground.png` — 中景
- `segments/background.png` — 背景
- `segments/depth_map.png` — 深度灰度图
- `segments/layers.json` — 图层配置（供 engine 使用）

### layers.json 格式

```json
[
  {"name": "foreground", "image_path": "/path/foreground.png", "z_depth": -1.5},
  {"name": "midground",  "image_path": "/path/midground.png",  "z_depth": 0.0},
  {"name": "background", "image_path": "/path/background.png", "z_depth": 7.5}
]
```

### 分层方案

| 方案 | 命令 | 说明 |
|------|------|------|
| MiDaS自动 | 默认 | `transformers` pipeline，~5s/4K图 |
| SAM2精确 | 需额外安装 | 更精准但更重 |
| 手动蒙版 | `--manual-mask` | PS黑白图，白色=保留 |

---

## 阶段二：视差渲染（Windows端）

<!-- FREEDOM:low -->

通过 **kais-blender-engine** 的 generator 模式执行：

```python
import sys
sys.path.insert(0, "/home/kai/.openclaw/workspace/skills/kais-blender-engine/client")

from blender_client import BlenderAgentClient
from generators.parallax import ParallaxParams, LayerConfig

cli = BlenderAgentClient("http://192.168.71.38:8080")

params = ParallaxParams(
    preset_name="scene_001",
    layers=[
        LayerConfig(name="foreground", image_path="D:/BlenderAgent/cache/parallax/foreground.png", z_depth=-1.5),
        LayerConfig(name="midground",  image_path="D:/BlenderAgent/cache/parallax/midground.png",  z_depth=0.0),
        LayerConfig(name="background", image_path="D:/BlenderAgent/cache/parallax/background.png", z_depth=7.5),
    ],
    camera_preset="scroll_left",
    duration=6.0,
    resolution=(1080, 1920),   # 9:16竖屏
    output_format="video",
    output_dir="D:/BlenderAgent/cache/parallax",
)

script = generate_parallax_script(params)
result = cli.run_sync(script, timeout=300)
print("状态:", result["status"])
print("输出:", result.get("outputs", []))
```

### 摄像机预设

| 预设 | 运动 | 适用场景 |
|------|------|----------|
| `scroll_left` | 横向平移←→，缓入缓出 | 场景展示、交代环境 |
| `scroll_right` | 反向平移→← | 反向展示 |
| `push_in` | 缓慢推进 | 聚焦主体 |
| `dolly_zoom` | 推近+缩小焦距 | Vertigo效果，戏剧性 |
| `orbit` | 环绕旋转90° | 物体而非场景 |
| `static` | 静态 | 仅输出分层场景图 |

### ParallaxParams 完整字段

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
| `engine` | str | `BLENDER_EEVEE_NEXT` | 渲染引擎 |
| `samples` | int | 64 | Cycles采样数 |
| `output_dir` | str | `D:/.../parallax` | Windows端输出目录 |

---

## 一键编排

```bash
# 分层 + 传输 + 渲染，全流程
python3 scripts/parallax_pipeline.py wide_image.png \
  --camera scroll_left \
  --duration 6.0 \
  --ratio 9:16 \
  --execute-remote
```

---

## 技术限制

| 限制 | 原因 | 缓解方案 |
|------|------|----------|
| 无法镜头穿过前景 | 2.5D本质是平面分层 | 限制摄像机Z轴移动 |
| 侧面视角穿帮 | 分层图只有正面信息 | 边缘延伸+模糊 |
| 动态元素（水、火） | 静态分层 | 结合视频生成工具 |
| 分割不完美 | AI模型局限 | `--manual-mask` 手动修正 |

---

## 文件结构

```
kais-parallax-scene/
├── SKILL.md                          # 本文件
├── scripts/
│   ├── depth_segment.py              # MiDaS深度估计+分层（Linux端）
│   └── parallax_pipeline.py          # 全流程编排
└── references/
    ├── parallax-math.md              # 视差计算数学原理
    └── midas-setup.md                # MiDaS模型安装指南

# 渲染能力由 kais-blender-engine 提供：
kais-blender-engine/client/
├── generators/
│   └── parallax.py                   # ParallaxParams + generate_parallax_script()
└── blender_client.py                 # run_sync() 执行
```
