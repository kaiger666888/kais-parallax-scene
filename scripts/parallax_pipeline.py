#!/usr/bin/env python3
"""
视差场景全流程编排 — 本地 GPU 执行

流程：
  步骤1: MiDaS 深度分层 (本地 GPU)
  步骤2: 视差/Ken Burns 合成 (本地 CPU/GPU)

用法:
  python3 parallax_pipeline.py --image-path ./wide.png --name scene_001
  python3 parallax_pipeline.py --image-path ./wide.png --camera scroll_left --duration 6.0
"""

import argparse
import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT_DIR = "/tmp/kais-parallax"


def run_local_segment(image_path, output_dir, layers=3, sigma=3.0):
    """本地运行 MiDaS 深度估计 + 分层。"""
    cmd = [
        sys.executable,
        os.path.join(SCRIPT_DIR, "depth_segment.py"),
        image_path,
        "-o", output_dir,
        "-l", str(layers),
        "--sigma", str(sigma),
    ]
    print(f"Running depth segmentation locally...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Segmentation failed:\n{result.stderr}")
        return None
    print(result.stdout)

    # 读取 layers.json
    json_path = os.path.join(output_dir, "layers.json")
    if not os.path.exists(json_path):
        print(f"ERROR: layers.json not found at {json_path}")
        return None

    with open(json_path) as f:
        return json.load(f)


def run_local_composite(image_dir, output_path, mode="auto", duration=6.0, fps=24,
                        parallax_strength=200, kenburns_zoom=1.1, kenburns_pan=80,
                        source=None, depth_threshold=0.12, width=None, height=None):
    """本地运行视差/Ken Burns 合成。"""
    cmd = [
        sys.executable,
        os.path.join(SCRIPT_DIR, "parallax_composite.py"),
        "--image-dir", image_dir,
        "-o", output_path,
        "--mode", mode,
        "--duration", str(duration),
        "--fps", str(fps),
        "--parallax-strength", str(parallax_strength),
        "--kenburns-zoom", str(kenburns_zoom),
        "--kenburns-pan", str(kenburns_pan),
        "--depth-threshold", str(depth_threshold),
    ]
    if source:
        cmd.extend(["--source", source])
    if width and height:
        cmd.extend(["--width", str(width), "--height", str(height)])

    print(f"Running parallax composite ({mode} mode)...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Composite failed:\n{result.stderr}")
        return None
    print(result.stdout)

    if os.path.exists(output_path):
        return output_path
    print("ERROR: output video not created")
    return None


def main():
    parser = argparse.ArgumentParser(description="2.5D视差场景全流程（本地执行）")
    parser.add_argument("--image-path", required=True, help="输入图片路径")
    parser.add_argument("-n", "--name", default="parallax_scene", help="输出文件名前缀")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT_DIR, help="输出根目录")
    parser.add_argument("-l", "--layers", type=int, default=3, choices=[2, 3, 4])
    parser.add_argument("--sigma", type=float, default=3.0, help="边缘羽化半径")
    parser.add_argument("--camera", default="scroll_left",
                        choices=["scroll_left", "scroll_right", "push_in", "dolly_zoom", "orbit", "static"])
    parser.add_argument("--duration", type=float, default=6.0)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--ratio", default="9:16", choices=["9:16", "16:9", "1:1"])
    parser.add_argument("--mode", default="auto", choices=["auto", "parallax", "kenburns"])
    parser.add_argument("--parallax-strength", type=int, default=200, help="视差偏移强度(px)")
    parser.add_argument("--kenburns-zoom", type=float, default=1.1, help="Ken Burns缩放倍率")
    parser.add_argument("--kenburns-pan", type=int, default=80, help="Ken Burns平移范围(px)")
    parser.add_argument("--source", default=None, help="Ken Burns用完整原图路径")
    parser.add_argument("--depth-threshold", type=float, default=0.12, help="自动模式景深方差阈值")
    args = parser.parse_args()

    image_path = os.path.abspath(args.image_path)
    if not os.path.exists(image_path):
        print(f"ERROR: 文件不存在: {image_path}")
        sys.exit(1)

    output_dir = os.path.join(args.output, args.name)
    segments_dir = os.path.join(output_dir, "segments")
    video_path = os.path.join(output_dir, f"{args.name}.mp4")

    resolution = {
        "9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)
    }[args.ratio]

    # Step 1: 深度分层 (本地 GPU)
    print(f"\n=== Step 1: Depth Segmentation ===")
    print(f"  Image: {image_path}")
    print(f"  Output: {segments_dir}")
    print(f"  Layers: {args.layers}")

    layer_config = run_local_segment(image_path, segments_dir, args.layers, args.sigma)
    if not layer_config:
        sys.exit(1)
    print(f"  Segmented into {len(layer_config)} layers")

    # Step 2: 视差合成 (本地)
    print(f"\n=== Step 2: Parallax Composite ===")
    print(f"  Mode: {args.mode}")
    print(f"  Duration: {args.duration}s @ {args.fps}fps")

    video = run_local_composite(
        segments_dir, video_path,
        mode=args.mode,
        duration=args.duration,
        fps=args.fps,
        parallax_strength=args.parallax_strength,
        kenburns_zoom=args.kenburns_zoom,
        kenburns_pan=args.kenburns_pan,
        source=args.source,
        depth_threshold=args.depth_threshold,
        width=resolution[0],
        height=resolution[1],
    )

    if video:
        size = os.path.getsize(video)
        print(f"\nDone!")
        print(f"  Video: {video} ({size / 1024:.0f}KB)")
        print(f"  Segments: {segments_dir}")
    else:
        print(f"\nFailed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
