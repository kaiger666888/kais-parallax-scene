#!/usr/bin/env python3
"""
MiDaS 深度估计 + 自动分层
输入：超宽图路径
输出：前景/中景/背景三张透明PNG + 深度图
"""

import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageFilter


def load_midas_model():
    """加载 MiDaS 深度估计模型"""
    try:
        import torch
        from transformers import AutoModelForImageSegmentation
    except ImportError:
        print("ERROR: 需要安装依赖: pip install torch transformers")
        sys.exit(1)

    # 使用 MiDaS v3.1 (DPT-Large)
    model_name = "Intel/dpt-large"
    print(f"Loading MiDaS model: {model_name}...")
    # 实际实现需要完整的MiDaS推理pipeline
    # 这里提供接口框架
    return None  # model


def estimate_depth(image_path):
    """
    生成深度图
    返回：numpy array, 值范围 [0, 1], 1=最近, 0=最远
    """
    try:
        import torch
        from transformers import pipeline
    except ImportError:
        print("ERROR: pip install torch transformers")
        sys.exit(1)

    img = Image.open(image_path).convert("RGB")

    # 使用 transformers 的 depth-estimation pipeline
    depth_estimator = pipeline("depth-estimation", model="Intel/dpt-large")
    result = depth_estimator(img)

    depth_image = result["depth"]
    depth_array = np.array(depth_image).astype(np.float64)

    # 归一化到 [0, 1]
    d_min, d_max = depth_array.min(), depth_array.max()
    if d_max > d_min:
        depth_array = (depth_array - d_min) / (d_max - d_min)
    else:
        depth_array = np.zeros_like(depth_array)

    # 反转：MiDaS输出中，小值=近，大值=远；我们需要反转
    depth_array = 1.0 - depth_array

    return depth_array


def segment_layers(image_path, depth_array, output_dir, num_layers=3):
    """
    根据深度图分割图层

    Args:
        image_path: 原始图片路径
        depth_array: 深度图 numpy array [0, 1]
        output_dir: 输出目录
        num_layers: 分层数量 (2-4)

    Returns:
        dict: {layer_name: output_path}
    """
    os.makedirs(output_dir, exist_ok=True)
    img = Image.open(image_path).convert("RGBA")
    img_array = np.array(img)

    # 深度阈值配置
    if num_layers == 2:
        thresholds = [0.5]
        layer_names = ["foreground", "background"]
    elif num_layers == 3:
        thresholds = [0.3, 0.8]
        layer_names = ["background", "midground", "foreground"]
    elif num_layers == 4:
        thresholds = [0.2, 0.5, 0.8]
        layer_names = ["distant", "background", "midground", "foreground"]
    else:
        raise ValueError(f"Unsupported num_layers: {num_layers}")

    # 创建图层
    results = {}
    prev_threshold = 0.0

    for i, (threshold, name) in enumerate(zip(thresholds, layer_names)):
        if i < len(thresholds) - 1:
            # 中间层
            mask = (depth_array >= prev_threshold) & (depth_array < threshold)
        else:
            # 最后一层（包含边界）
            mask = depth_array >= prev_threshold

        # 边缘羽化
        mask_float = mask.astype(np.float64)
        from scipy.ndimage import gaussian_filter
        mask_float = gaussian_filter(mask_float, sigma=3)
        mask_float = (mask_float * 255).astype(np.uint8)

        # 应用蒙版
        layer = img_array.copy()
        layer[:, :, 3] = mask_float  # Alpha通道

        # 保存
        out_path = os.path.join(output_dir, f"{name}.png")
        Image.fromarray(layer).save(out_path)
        results[name] = out_path
        print(f"  ✅ {name}: {out_path}")

        prev_threshold = threshold

    # 保存深度图
    depth_vis = (depth_array * 255).astype(np.uint8)
    depth_path = os.path.join(output_dir, "depth_map.png")
    Image.fromarray(depth_vis).save(depth_path)
    results["depth_map"] = depth_path
    print(f"  ✅ depth_map: {depth_path}")

    return results


def main():
    parser = argparse.ArgumentParser(description="MiDaS深度估计+自动分层")
    parser.add_argument("image", help="输入图片路径")
    parser.add_argument("-o", "--output", default=None, help="输出目录（默认: 同目录/segments/）")
    parser.add_argument("-l", "--layers", type=int, default=3, choices=[2, 3, 4], help="分层数量")
    parser.add_argument("--manual-mask", help="手动蒙版路径（黑白图，跳过AI分割）")
    args = parser.parse_args()

    if not os.path.exists(args.image):
        print(f"ERROR: 文件不存在: {args.image}")
        sys.exit(1)

    output_dir = args.output or os.path.join(os.path.dirname(args.image), "segments")

    print(f"📷 输入: {args.image}")
    print(f"📁 输出: {output_dir}")
    print(f"🎯 分层数: {args.layers}")

    if args.manual_mask:
        # 使用手动蒙版
        mask_img = Image.open(args.manual_mask).convert("L")
        depth_array = np.array(mask_img).astype(np.float64) / 255.0
        print("✅ 使用手动蒙版")
    else:
        # AI自动分割
        print("🔍 正在生成深度图...")
        depth_array = estimate_depth(args.image)
        print("✅ 深度图生成完成")

    print("✂️ 正在分割图层...")
    results = segment_layers(args.image, depth_array, output_dir, args.layers)
    print(f"\n🎉 完成！共生成 {len(results)} 个文件")

    # 输出JSON供下游使用
    import json
    json_path = os.path.join(output_dir, "layers.json")
    # 转换为layer_z格式供Blender使用
    layer_z_map = {
        "foreground": -1.5,
        "midground": 0.0,
        "background": 7.5,
        "distant": 20.0,
    }
    layer_config = []
    for name, path in results.items():
        if name == "depth_map":
            continue
        layer_config.append({
            "name": name,
            "image_path": path,
            "z_depth": layer_z_map.get(name, 0.0),
        })

    with open(json_path, "w") as f:
        json.dump(layer_config, f, indent=2, ensure_ascii=False)
    print(f"📋 图层配置: {json_path}")

    return results


if __name__ == "__main__":
    main()
