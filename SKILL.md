---
name: kais-parallax-scene
version: 0.6.0
description: "AI视差场景生成器。两种模式：(1)AI三步法：即梦文生图→图生图分层→视差合成；(2)深度分层法：MiDaS GPU分层→视差/Ken Burns合成。全部本地Linux执行。触发词：视差场景, parallax, 2.5D场景, AI视差, parallax scene, 视差动画, 景深分层, 场景分层, 即梦宽图, parallax animation, 视差生成"
---

# kais-parallax-scene — AI视差场景生成器

> **两种管线模式**：
>
> | 模式 | 流程 | 适用场景 | 质量 |
> |------|------|----------|------|
> | **AI三步法** | 即梦文生图 → 图生图(背景+前景) → rembg抠图 → 视差合成 | 任意场景，无分割重影 | ⭐⭐⭐⭐⭐ |
> | **深度分层法** | MiDaS GPU分层 → 视差/Ken Burns合成 | 有明确景深的场景 | ⭐⭐⭐ |
>
> **推荐AI三步法**：AI生成独立的背景和前景图，彻底避免分割重影和黑块问题。

## 前置依赖

### AI三步法
- **jimeng-free-api** Docker 容器运行中（`localhost:8000`）
- **即梦 session ID**（环境变量 `JIMENG_SESSION_ID` 或 Docker 容器内获取）
- **rembg** — `pip install "rembg[gpu]"`
- **numpy** + **Pillow** + **ffmpeg**

### 深度分层法
- **torch** 2.6+ (CUDA) — `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124`
- **transformers** — `pip install transformers`
- **scipy** — `pip install scipy`
- **Pillow** + **ffmpeg**

## 管线位置

```
即梦/SD 超宽图 ──→ [kais-parallax-scene] ──→ 动态镜头视频
                         │
                     全部本地执行
                         │
              ┌──────────┴──────────┐
         MiDaS深度分层(GPU)    视差/Ken Burns合成
              │                      │
         分层PNG + layers.json   FFmpeg → MP4
```

**与 kais-hub 的关系**：
- 通过 kais-hub 的 ToolAdapter 框架集成，作为 `parallax_generation` task type
- 共享 GPU 信号量，与其他 GPU 任务串行执行

---

## ⭐ AI三步法管线

```
用户图/即梦文生图 ──→ 即梦图生图(背景21:9) ──→ 即梦图生图(前景16:9) ──→ rembg抠图 ──→ 视差合成 ──→ MP4
       ①                     ②a                      ②b                   ③a            ③b
```

**步骤1支持两种输入**：
- **用户图**（`--source-image`）：直接用用户的图进入步骤2
- **文生图**（`--prompt`）：即梦AI生成场景图后进入步骤2

### 一键执行

```bash
# 方式A: 用户已有图，直接分层
python3 scripts/ai_parallax_pipeline.py \
  --source-image ./coffee_shop.png \
  --prompt "A cozy coffee shop interior" \
  -o coffee_parallax.mp4

# 方式B: 纯AI生成
python3 scripts/ai_parallax_pipeline.py \
  --prompt "A cozy coffee shop interior, warm lighting, wooden tables, photorealistic" \
  -o output.mp4
```

---

## 深度分层法

```
步骤一：GPU深度分层              步骤二：合成
──────────────────────────────────────────────
超宽图.png → MiDaS(CUDA)  →     parallax_composite.py
           前景/中景/背景PNG  →    双模式自动选择
           layers.json          FFmpeg → MP4
```

### 一键执行

```bash
# 全流程（本地执行）
python3 scripts/parallax_pipeline.py \
  --image-path ./wide.png \
  --name scene_001 \
  --camera scroll_left \
  --duration 6.0 \
  --ratio 9:16

# 仅深度分层
python3 scripts/depth_segment.py ./wide.png -o ./segments -l 3

# 仅合成（需要已有分层图）
python3 scripts/parallax_composite.py --image-dir ./segments -o output.mp4
```

### 摄像机预设（管线编排用）

| 预设 | 运动 | 适用场景 |
|------|------|----------|
| `scroll_left` | 横向平移←→，缓入缓出 | 场景展示、交代环境 |
| `scroll_right` | 反向平移→← | 反向展示 |
| `push_in` | 缓慢推进 | 聚焦主体 |
| `dolly_zoom` | 推近+缩小焦距 | Vertigo效果 |
| `orbit` | 环绕旋转90° | 物体展示 |
| `static` | 静态 | 仅输出分层场景图 |

---

## 双模式自动选择

合成引擎根据**深度图方差**自动选择最佳模式：

| 模式 | 条件 | 效果 | 适用场景 |
|------|------|------|----------|
| **视差偏移** | `depth_variance > 0.12` | 各层按深度不同偏移 | 风景、户外、有纵深感 |
| **Ken Burns** | `depth_variance ≤ 0.12` | 缓慢缩放+平移 | 室内、平坦、浅景深 |

```bash
# 强制视差
python3 scripts/parallax_composite.py --image-dir <dir> --mode parallax -o out.mp4
# 强制Ken Burns
python3 scripts/parallax_composite.py --image-dir <dir> --mode kenburns -o out.mp4
# 自动选择（默认）
python3 scripts/parallax_composite.py --image-dir <dir> -o out.mp4
```

---

## 硬件需求

| 步骤 | 资源 | 说明 |
|------|------|------|
| MiDaS分层 | GPU VRAM 2-3GB, ~1s/张 | RTX 3060 Ti ✅ |
| rembg抠图 | GPU VRAM ~0.5GB | ONNX Runtime |
| FFmpeg合成 | CPU | 帧序列编码 |

## 技术限制

| 限制 | 缓解方案 |
|------|----------|
| 无法镜头穿过前景 | 限制摄像机Z轴移动 |
| 侧面视角穿帮 | 边缘延伸10%+模糊 |
| 动态元素（水、火） | 结合视频生成工具 |
| 分割不完美 | 手动提供蒙版 |

---

## 文件结构

```
kais-parallax-scene/
├── SKILL.md                          # 本文件
├── scripts/
│   ├── ai_parallax_pipeline.py       # ⭐ AI三步法管线（推荐）
│   ├── depth_segment.py              # 深度分层脚本（MiDaS GPU，自动检测）
│   ├── parallax_composite.py         # 双模式合成引擎
│   └── parallax_pipeline.py          # 深度分层全流程编排（本地执行）
└── references/
    ├── parallax-math.md              # 视差数学原理
    └── midas-setup.md                # MiDaS安装指南
```
