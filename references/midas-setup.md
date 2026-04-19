# MiDaS 模型安装指南

## 方案一：transformers Pipeline（推荐）

```bash
pip install torch torchvision transformers scipy
```

使用 Intel DPT-Large 模型，首次运行自动下载（~1.3GB）。

## 方案二：timm + MiDaS 原版

```bash
pip install timm
```

```python
import torch
import timm
from PIL import Image

model = timm.create_model('vit_large_patch14_224.dinov2.unsupervised', pretrained=True)
```

## 方案三：ONNX Runtime（最轻量）

```bash
pip install onnxruntime
```

下载预编译ONNX模型，无需PyTorch。

## 硬件要求

| 模型 | VRAM | 速度(4K图) | 精度 |
|------|------|-----------|------|
| MiDaS Small | <2GB | ~2s | 中 |
| DPT-Large | 4-6GB | ~5s | 高 |
| DPT-Hybrid | 6-8GB | ~8s | 最高 |

## 离线使用

```bash
# 预下载模型
python -c "from transformers import pipeline; pipeline('depth-estimation', model='Intel/dpt-large')"

# 模型缓存位置
~/.cache/huggingface/hub/models--Intel--dpt-large/
```
