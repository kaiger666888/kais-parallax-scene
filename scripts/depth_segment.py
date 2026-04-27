#!/usr/bin/env python3
"""
MiDaS 深度估计 + 自动分层（GPU 加速）

输入：超宽图路径
输出：前景/中景/背景透明 PNG + 深度图 + layers.json
"""

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageFilter


def estimate_depth(image_path):
    """MiDaS 深度估计，自动检测 GPU。

    返回：numpy array, 值范围 [0, 1], 1=最近, 0=最远
    """
    import torch
    from transformers import pipeline

    device = 0 if torch.cuda.is_available() else -1
    print(f"Loading MiDaS model (device={'cuda' if device == 0 else 'cpu'})...")
    pipe = pipeline("depth-estimation", model="Intel/dpt-large", device=device)

    print(f"Processing: {image_path}")
    img = Image.open(image_path).convert("RGB")
    result = pipe(img)
    depth_image = result["depth"]

    depth_array = np.array(depth_image).astype(np.float64)

    d_min, d_max = depth_array.min(), depth_array.max()
    if d_max > d_min:
        depth_array = (depth_array - d_min) / (d_max - d_min)
    else:
        depth_array = np.zeros_like(depth_array)

    # 反转：MiDaS 小值=近，我们需要近=大值
    depth_array = 1.0 - depth_array
    return depth_array


def segment_layers(image_path, depth_array, output_dir, num_layers=3, edge_bleed_sigma=3):
    """根据深度图分割图层。"""
    from scipy.ndimage import gaussian_filter

    os.makedirs(output_dir, exist_ok=True)
    img = Image.open(image_path).convert("RGBA")
    img_array = np.array(img)

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

    all_thresholds = [0.0] + thresholds + [1.01]
    results = {}

    for i, name in enumerate(layer_names):
        low = all_thresholds[i]
        high = all_thresholds[i + 1]
        mask = (depth_array >= low) & (depth_array < high)

        mask_float = mask.astype(np.float64)
        mask_float = gaussian_filter(mask_float, sigma=edge_bleed_sigma)
        mask_float = (mask_float * 255).astype(np.uint8)

        layer = img_array.copy()
        layer[:, :, 3] = mask_float

        out_path = os.path.join(output_dir, f"{name}.png")
        Image.fromarray(layer).save(out_path)
        results[name] = out_path
        print(f"  {name}: {out_path}")

    # 深度图
    depth_vis = (depth_array * 255).astype(np.uint8)
    depth_path = os.path.join(output_dir, "depth_map.png")
    Image.fromarray(depth_vis).save(depth_path)
    results["depth_map"] = depth_path
    print(f"  depth_map: {depth_path}")

    return results


def main():
    parser = argparse.ArgumentParser(description="MiDaS深度估计+自动分层")
    parser.add_argument("image", help="输入图片路径")
    parser.add_argument("-o", "--output", default=None, help="输出目录（默认: 同目录/segments/）")
    parser.add_argument("-l", "--layers", type=int, default=3, choices=[2, 3, 4], help="分层数量")
    parser.add_argument("--sigma", type=float, default=3.0, help="边缘羽化半径")
    parser.add_argument("--manual-mask", help="手动蒙版路径（黑白图，跳过AI分割）")
    args = parser.parse_args()

    if not os.path.exists(args.image):
        print(f"ERROR: 文件不存在: {args.image}")
        sys.exit(1)

    output_dir = args.output or os.path.join(os.path.dirname(args.image), "segments")

    print(f"Input: {args.image}")
    print(f"Output: {output_dir}")
    print(f"Layers: {args.layers}")

    if args.manual_mask:
        mask_img = Image.open(args.manual_mask).convert("L")
        depth_array = np.array(mask_img).astype(np.float64) / 255.0
        print("Using manual mask")
    else:
        print("Running depth estimation...")
        depth_array = estimate_depth(args.image)
        print("Depth estimation done")

    print("Segmenting layers...")
    results = segment_layers(args.image, depth_array, output_dir, args.layers, args.sigma)
    print(f"Complete: {len(results)} files")

    # 输出 layers.json
    layer_z_map = {"foreground": -1.5, "midground": 0.0, "background": 7.5, "distant": 20.0}
    layer_config = []
    for name, path in results.items():
        if name == "depth_map":
            continue
        layer_config.append({"name": name, "image_path": path, "z_depth": layer_z_map.get(name, 0.0)})

    json_path = os.path.join(output_dir, "layers.json")
    with open(json_path, "w") as f:
        json.dump(layer_config, f, indent=2, ensure_ascii=False)
    print(f"layers.json: {json_path}")

    return results


if __name__ == "__main__":
    main()
