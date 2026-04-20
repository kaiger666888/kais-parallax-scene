"""
Windows端深度分层脚本 — 通过 kais-blender-engine 的 run_async() 远程执行

在Windows端运行，使用GPU加速MiDaS深度估计，输出分层PNG到指定目录。
"""

import argparse
import json
import os
import sys


def estimate_depth(image_path):
    """MiDaS深度估计，优先GPU"""
    from transformers import pipeline

    print(f"🔍 Loading MiDaS model (GPU={__import__('torch').cuda.is_available()})...")
    pipe = pipeline("depth-estimation", model="Intel/dpt-large", device=0 if __import__('torch').cuda.is_available() else -1)

    print(f"📷 Processing: {image_path}")
    from PIL import Image
    img = Image.open(image_path).convert("RGB")
    result = pipe(img)
    depth_image = result["depth"]

    import numpy as np
    depth_array = np.array(depth_image).astype(np.float64)

    d_min, d_max = depth_array.min(), depth_array.max()
    if d_max > d_min:
        depth_array = (depth_array - d_min) / (d_max - d_min)
    else:
        depth_array = np.zeros_like(depth_array)

    # 反转：MiDaS小值=近，我们需要近=大值
    depth_array = 1.0 - depth_array
    return depth_array


def segment_layers(image_path, depth_array, output_dir, num_layers=3, edge_bleed_sigma=3):
    """根据深度图分割图层"""
    import numpy as np
    from PIL import Image
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
        print(f"  ✅ {name}: {out_path}")

    # 深度图
    depth_vis = (depth_array * 255).astype(np.uint8)
    depth_path = os.path.join(output_dir, "depth_map.png")
    Image.fromarray(depth_vis).save(depth_path)
    results["depth_map"] = depth_path
    print(f"  ✅ depth_map: {depth_path}")

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image", help="输入图片路径(Windows)")
    parser.add_argument("-o", "--output", required=True, help="输出目录(Windows)")
    parser.add_argument("-l", "--layers", type=int, default=3, choices=[2, 3, 4])
    parser.add_argument("--sigma", type=float, default=3.0, help="边缘羽化半径")
    args = parser.parse_args()

    print(f"📷 Input: {args.image}")
    print(f"📁 Output: {args.output}")
    print(f"🎯 Layers: {args.layers}")

    depth_array = estimate_depth(args.image)
    print("✅ Depth estimation done")

    results = segment_layers(args.image, depth_array, args.output, args.layers, args.sigma)
    print(f"🎉 Segmentation complete: {len(results)} files")

    # 输出 layers.json
    layer_z_map = {"foreground": -1.5, "midground": 0.0, "background": 7.5, "distant": 20.0}
    layer_config = []
    for name, path in results.items():
        if name == "depth_map":
            continue
        layer_config.append({"name": name, "image_path": path, "z_depth": layer_z_map.get(name, 0.0)})

    json_path = os.path.join(args.output, "layers.json")
    with open(json_path, "w") as f:
        json.dump(layer_config, f, indent=2, ensure_ascii=False)
    print(f"📋 layers.json: {json_path}")


if __name__ == "__main__":
    main()
