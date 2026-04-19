---
name: kais-parallax-scene
version: 0.1.0
description: "2.5D视差场景生成器。将即梦/SD超宽图自动分层，通过Blender Geometry Nodes构建视差场景，生成动态镜头视频。与kais-blender-layout（场景规划）和kais-blender-engine（渲染执行）配合使用，构成完整的2D→2.5D→动态视频管线。触发词：视差场景, parallax, 2.5D场景, 宽图分层, parallax scene, 视差动画, 景深分层, 场景分层, 即梦宽图, 超宽图分层, parallax animation, 视差生成"
---

# kais-parallax-scene — 2.5D 视差场景生成器

> 将即梦/SD超宽图（21:9 / 32:9）自动分层为前景/中景/背景，
> 通过 Blender Geometry Nodes 构建视差场景，生成动态镜头视频。
>
> **核心价值**：用一张静态超宽图 + AI分割，模拟大角度场景动态镜头，
> 避免全3D建模的高成本，适合AI短剧批量生产。

## 前置依赖

<!-- FREEDOM:low -->

- **Windows 端**：Blender Agent Server 运行中（由 kais-blender-engine 提供）
- **Python 依赖**：`pip install requests numpy Pillow`
- **AI 分割模型**（Linux 端执行）：
  - 推荐：`pip install torch torchvision` + `transformers`（MiDaS 深度估计）
  - 备选：`segment-anything-2`（SAM2，更精准但更重）
  - 最简方案：支持用户手动提供蒙版（PS绘制黑白图）

---

## 管线位置

```
即梦/SD 超宽图 ──→ [kais-parallax-scene] ──→ Blender .blend + 渲染视频
     │                       │
     │                    分层+视差
     │                       │
     └── kais-blender-layout ─┘  (可选：layout提供场景蓝图，复用engine)
              │
         kais-blender-engine  (渲染执行)
```

**与 kais-blender-layout 的关系**：
- layout 负责"3D资产场景"（角色+家具+HDRI建模渲染）
- parallax-scene 负责"2D超宽图→2.5D动态"（AI绘图分层+视差动画）
- 两者共享 kais-blender-engine 的渲染能力

**与 kais-blender-engine 的关系**：
- parallax-scene 通过 engine 的 HTTP API 提交 Blender Python 脚本执行
- engine 提供渲染能力（Cycles/Eevee）、输出格式、分辨率控制

---

## 全流程概览

```
阶段一：输入获取     阶段二：智能分层     阶段三：场景构建     阶段四：渲染输出
─────────────────────────────────────────────────────────────────────────────
超宽图(.png)  ──→  前景/中景/背景  ──→  Blender Geometry  ──→  动态镜头视频
深度图(可选)       蒙版(.png)         Nodes 场景文件          (.blend + .mp4)
即梦API
```

---

## 阶段一：输入获取

### 输入规格

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `source` | 本地路径 | 图片来源：本地路径 / 即梦API生成 |
| `image_size` | 6198×2656 | 21:9 4K |
| `aspect_ratio` | 21:9 | 支持 21:9、32:9 |
| `output_ratio` | 9:16 | 输出画幅：9:16竖屏 / 16:9横屏 / 1:1方形 |
| `output_resolution` | 1080×1920 | 竖屏HD，可调至 2160×3840 (4K) |

### 即梦 API 集成（可选）

如果使用即梦生成超宽图，先通过即梦API生成21:9/32:9宽图，再进入分层流程。
即梦API由 `kais-evolink` 或直接调用 `jimeng-free-api` 提供。

---

## 阶段二：智能分层

<!-- FREEDOM:low -->

### 方案 A：自动深度估计（推荐）

使用 MiDaS 单目深度估计模型，零人工干预：

```python
# scripts/depth_segment.py
# 输入：超宽图路径
# 输出：前景/中景/背景三张PNG（透明背景）+ 深度图

def auto_layer_segment(image_path, output_dir):
    """
    基于MiDaS深度图进行三层分割
    - 前景 (Foreground): 深度值 > 0.8（最近处20%）
    - 中景 (Midground):   深度值 0.3~0.8（中间50%）
    - 背景 (Background):  深度值 < 0.3（最远处30%）
    """
    # 1. 加载MiDaS模型
    # 2. 生成深度图
    # 3. 根据阈值分割为三层
    # 4. 边缘羽化（feather 3-5px）减少硬边
    # 5. 保存为透明PNG
```

### 方案 B：SAM2 精确分割

更精准但计算量更大，适合前景主体清晰的场景。

### 方案 C：手动蒙版

用户提供黑白蒙版图（白色=保留，黑色=透明），跳过AI分割。

### 边缘处理（防穿帮）

每层边缘向外延伸 **10%**（`edge_bleed: 0.1`），用 `content-aware fill` 或 `边缘模糊` 补充被裁切区域。

---

## 阶段三：场景构建

<!-- FREEDOM:low -->

### Blender Python 脚本生成

在 Linux 端生成 Blender Python 脚本，通过 kais-blender-engine 的 HTTP API 发送到 Windows 执行。

**核心逻辑**：

```python
# 1. 创建4个Plane几何体（前景/中景/背景/远景）
# 2. 每层加载对应的分层PNG作为纹理
# 3. 根据Z深度调整缩放：scale = 1 + (abs(Z) / focal_length)
# 4. UV展开保持原始像素比例
# 5. 设置摄像机动画（平移/推轨/环绕）
```

### 视差计算公式

```python
def calculate_parallax(layer_z, camera_move_x, focal_length=35):
    """
    视差位移量计算
    Z越远的层，在摄像机移动时位移越小（视差越小）
    """
    parallax_factor = focal_length / (focal_length + abs(layer_z))
    return camera_move_x * (1 - parallax_factor)
```

### 层级深度设置

| 层 | Z 深度 | 缩放补偿 | 说明 |
|----|--------|----------|------|
| 前景 | -2.0m ~ -1.0m | 1.06 ~ 1.03 | 最近，视差最大 |
| 中景 | 0m | 1.0 | 基准平面 |
| 背景 | 5.0m ~ 10.0m | 1.14 ~ 1.29 | 远景，视差小 |
| 远景（可选） | 20m+ | 1.57+ | 天空/远景，几乎不动 |

### 摄像机预设模板

| 预设 | 运动 | 参数 | 适用场景 |
|------|------|------|----------|
| `scroll_left` | 横向平移 | X: -3m→+3m, 6秒, 缓入缓出 | 场景展示、交代环境 |
| `scroll_right` | 反向平移 | X: +3m→-3m, 6秒 | 反向展示 |
| `dolly_zoom` | 推轨变焦 | 推近+缩小焦距, 4秒 | Vertigo效果，戏剧性 |
| `push_in` | 缓慢推进 | Z: -5m→-2m, 4秒 | 聚焦主体 |
| `orbit` | 环绕展示 | 绕Y轴旋转90°, 8秒 | 物体而非场景 |
| `static` | 静态渲染 | 无动画 | 仅输出分层场景 |

---

## 阶段四：渲染输出

通过 kais-blender-engine HTTP API 提交渲染任务：

```python
import sys
sys.path.insert(0, "/home/kai/.openclaw/workspace/skills/kais-blender-engine/client")
from blender_client import BlenderAgentClient

cli = BlenderAgentClient("http://192.168.71.38:8080")

# 提交视差场景渲染脚本
result = cli.execute_script(
    script_path="/tmp/parallax_scene.py",
    timeout=300
)
```

### 输出规格

- `.blend` 文件：保留完整编辑能力（可手动调整）
- 渲染视频：MP4 (H.264)，支持 9:16 / 16:9 / 1:1
- 帧序列：PNG（可选，用于后期合成）

---

## 使用方式

### 基本调用

```
用户：帮我把这张超宽图做成视差场景动画
Agent：[自动执行四阶段流程]
```

### 完整参数示例

```yaml
# 输入配置
kais-parallax-scene:
  input:
    source: "/path/to/wide_image.png"
    aspect_ratio: "21:9"

  processing:
    segmentation: "midas"    # midas / sam2 / manual_mask
    layers: 3                # 2-4层
    edge_bleed: 0.1          # 10%边缘延伸

  camera:
    preset: "scroll_left"
    duration: 6.0

  output:
    blend_file: true
    render_video: true
    resolution: "1080x1920"  # 9:16竖屏
```

### 与 kais-blender-layout 联合使用

```
用户：这个场景用parallax方案，角色部分用layout的3D方案
Agent：
  1. [parallax-scene] 处理环境背景（超宽图→分层→视差）
  2. [blender-layout] 处理角色（场景蓝图→3D建模→渲染）
  3. [blender-engine] 合成输出最终视频
```

---

## 技术限制

| 限制 | 原因 | 缓解方案 |
|------|------|----------|
| 无法处理镜头穿过前景 | 2.5D本质是平面分层 | 限制摄像机Z轴移动范围 |
| 侧面视角穿帮 | 分层图只有正面信息 | 边缘延伸+模糊处理 |
| 动态元素（水、火焰） | 静态分层无法表现 | 结合视频生成工具 |
| 精细遮挡关系 | AI分割可能不完美 | 支持手动蒙版修正 |

---

## 文件结构

```
kais-parallax-scene/
├── SKILL.md                    # 本文件
├── scripts/
│   ├── depth_segment.py        # MiDaS深度估计+分层
│   ├── generate_blend.py       # 生成Blender Python脚本
│   └── parallax_pipeline.py    # 全流程编排
├── references/
│   ├── parallax-math.md        # 视差计算数学原理
│   └── midas-setup.md          # MiDaS模型安装指南
└── client/
    └── parallax_client.py      # 高层API封装
```

---

## 质量检查清单

- [ ] 分层边缘无明显硬边（羽化3-5px）
- [ ] 摄像机运动平滑（缓入缓出）
- [ ] 远景层无明显视差跳动
- [ ] 输出画幅正确（9:16/16:9）
- [ ] 前景边缘无穿帮（边缘延伸生效）
- [ ] .blend文件可手动打开编辑
