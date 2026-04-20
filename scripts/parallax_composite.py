#!/usr/bin/env python3
"""
视差场景合成引擎 — 双模式

模式自动选择：
- 景深丰富（depth_variance > threshold）→ 视差分层偏移
- 景深平坦（depth_variance ≤ threshold）→ Ken Burns（缩放+平移）

用法:
  python parallax_composite.py --image-dir <分层目录> --output <输出mp4> --duration 3
  python parallax_composite.py --image-dir <分层目录> --mode parallax --output <输出mp4>
  python parallax_composite.py --image-dir <分层目录> --mode kenburns --output <输出mp4>
"""

import argparse
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image


def load_layers(image_dir):
    """加载分层图和深度图"""
    layers = {}
    for name in ["foreground", "midground", "background", "distant"]:
        path = os.path.join(image_dir, f"{name}.png")
        if os.path.exists(path):
            layers[name] = np.array(Image.open(path).convert("RGBA"))

    depth_path = os.path.join(image_dir, "depth_map.png")
    depth = None
    if os.path.exists(depth_path):
        depth = np.array(Image.open(depth_path).convert("L")).astype(np.float32) / 255.0

    return layers, depth


def calc_depth_variance(depth):
    """计算深度图方差（0=平坦, 1=景深丰富）"""
    if depth is None:
        return 0.5  # 未知则默认中等
    return float(np.std(depth))


def alpha_composite(canvas, overlay, shift_x=0, shift_y=0):
    """将overlay以shift偏移叠加到canvas上（alpha混合）"""
    h, w = canvas.shape[:2]
    oh, ow = overlay.shape[:2]

    x1s = max(0, shift_x)
    x1d = max(0, -shift_x)
    y1s = max(0, shift_y)
    y1d = max(0, -shift_y)
    x2s = min(ow, ow + shift_x)
    x2d = min(w, w - shift_x)
    y2s = min(oh, oh + shift_y)
    y2d = min(h, h - shift_y)

    if x2s <= x1s or x2d <= x1d or y2s <= y1s or y2d <= y1d:
        return canvas

    a = overlay[y1s:y2s, x1s:x2s, 3:4].astype(np.float32) / 255.0
    if a.ndim == 3:
        a = a[:, :, 0]

    for c in range(3):
        canvas[y1d:y2d, x1d:x2d, c] = np.clip(
            a * overlay[y1s:y2s, x1s:x2s, c] + (1 - a) * canvas[y1d:y2d, x1d:x2d, c],
            0, 255
        ).astype(np.uint8)
    canvas[y1d:y2d, x1d:x2d, 3] = np.clip(
        a * 255 + (1 - a) * canvas[y1d:y2d, x1d:x2d, 3],
        0, 255
    ).astype(np.uint8)
    return canvas


def parallax_composite(layers, output_dir, frames, parallax_strength=200):
    """视差模式：各层按深度不同偏移"""
    midground = layers.get("midground")
    if midground is None:
        # 用最大的层作为基准
        midground = max(layers.values(), key=lambda l: (l[:, :, 3] > 128).sum())

    h, w = midground.shape[:2]

    # 各层偏移量（近→远递减）
    shift_map = {
        "foreground": parallax_strength,
        "midground": 0,
        "background": -parallax_strength * 0.25,
        "distant": -parallax_strength * 0.5,
    }

    for i in range(frames):
        t = (i / max(1, frames - 1)) - 0.5  # -0.5 ~ 0.5
        canvas = midground.copy()

        for name in ["distant", "background", "foreground"]:
            layer = layers.get(name)
            if layer is None:
                continue
            shift = int(t * shift_map[name])
            canvas = alpha_composite(canvas, layer, shift_x=shift)

        Image.fromarray(canvas).save(f"{output_dir}/{i + 1:04d}.png")


def kenburns_composite(layers, output_dir, frames, zoom=1.15, pan_range=100):
    """Ken Burns模式：缓慢缩放+平移，单张图效果"""
    # 用中景（或最大层）作为源图
    source = layers.get("midground")
    if source is None:
        source = max(layers.values(), key=lambda l: (l[:, :, 3] > 128).sum())

    h, w = source.shape[:2]
    output_w, output_h = w, h

    for i in range(frames):
        t = i / max(1, frames - 1)  # 0~1

        # 缩放：从1.0到zoom
        scale = 1.0 + (zoom - 1.0) * t
        new_w = int(w * scale)
        new_h = int(h * scale)

        # 先放大
        scaled = np.array(Image.fromarray(source).resize((new_w, new_h), Image.LANCZOS))

        # 平移（从一侧缓慢移到另一侧）
        pan = int(pan_range * (t - 0.5))
        x1 = max(0, pan)
        x2 = min(output_w, pan + output_w)

        canvas = np.zeros((output_h, output_w, 4), dtype=np.uint8)
        if x2 > x1:
            cw = min(x2, new_w) - x1
            ch = min(output_h, new_h)
            if cw > 0 and ch > 0:
                canvas[:ch, x1:x1 + cw] = scaled[:ch, :cw]

        Image.fromarray(canvas).save(f"{output_dir}/{i + 1:04d}.png")


def frames_to_video(output_dir, video_path, fps=24, width=None, height=None):
    """帧序列→MP4"""
    vf = ""
    if width and height:
        vf = f" -vf \"scale={width}:{height}\""
    cmd = f'ffmpeg -y -framerate {fps} -i "{output_dir}/%04d.png" -c:v libx264 -pix_fmt yuv420p{vf} "{video_path}"'
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if os.path.exists(video_path):
        return video_path
    else:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-300:]}")


def main():
    parser = argparse.ArgumentParser(description="视差/Ken Burns双模式合成")
    parser.add_argument("--image-dir", required=True, help="分层图目录")
    parser.add_argument("-o", "--output", required=True, help="输出MP4路径")
    parser.add_argument("--mode", default="auto", choices=["auto", "parallax", "kenburns"])
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--parallax-strength", type=int, default=200, help="视差偏移强度(px)")
    parser.add_argument("--kenburns-zoom", type=float, default=1.15, help="Ken Burns缩放倍率")
    parser.add_argument("--kenburns-pan", type=int, default=100, help="Ken Burns平移范围(px)")
    parser.add_argument("--depth-threshold", type=float, default=0.12, help="自动模式景深方差阈值")
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    args = parser.parse_args()

    layers, depth = load_layers(args.image_dir)
    if not layers:
        print(f"ERROR: No layers found in {args.image_dir}")
        sys.exit(1)

    frames = int(args.duration * args.fps)

    # 自动模式：根据景深方差选择
    if args.mode == "auto":
        variance = calc_depth_variance(depth)
        if variance > args.depth_threshold:
            args.mode = "parallax"
        else:
            args.mode = "kenburns"
        print(f"📊 景深方差={variance:.3f} (阈值={args.depth_threshold}) → {args.mode}模式")

    # 临时帧目录
    frames_dir = args.output.rsplit(".", 1)[0] + "_frames"
    os.makedirs(frames_dir, exist_ok=True)

    if args.mode == "parallax":
        parallax_composite(layers, frames_dir, frames, args.parallax_strength)
    else:
        kenburns_composite(layers, frames_dir, frames, args.kenburns_zoom, args.kenburns_pan)

    # 合成视频
    video_path = frames_to_video(frames_dir, args.output, args.fps, args.width, args.height)
    size = os.path.getsize(video_path)
    print(f"✅ {args.mode}模式: {video_path} ({size}B, {args.duration}s, {frames}frames)")

    return video_path


if __name__ == "__main__":
    main()
