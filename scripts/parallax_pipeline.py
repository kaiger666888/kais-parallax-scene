#!/usr/bin/env python3
"""
视差场景全流程编排 — 全部在Windows端执行

用法:
  python3 parallax_pipeline.py --image-path "D:/path/to/wide.png" --execute-remote
  
  或通过engine API直接调用（推荐）
"""

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_CLIENT_DIR = os.path.expanduser("~/.openclaw/workspace/skills/kais-blender-engine/client")
ENGINE_HOST = "http://192.168.71.38:8080"

# depth_segment_win.py 在Windows端的路径
WIN_SEGMENT_SCRIPT = "C:/Users/Kai/depth_segment_win.py"

# 默认输出目录
WIN_OUTPUT_DIR = "D:/BlenderAgent/cache/parallax"


def run_remote_segment(image_path, output_dir, layers=3):
    """在Windows端运行MiDaS深度估计+分层"""
    sys.path.insert(0, ENGINE_CLIENT_DIR)
    from blender_client import BlenderAgentClient

    cli = BlenderAgentClient(ENGINE_HOST)
    
    # 读取本地脚本内容，通过engine远程执行
    script_path = os.path.join(SCRIPT_DIR, "depth_segment_win.py")
    with open(script_path) as f:
        segment_script = f.read()

    # 构建执行命令
    cmd = f"""
import sys
sys.argv = ["depth_segment_win.py", "{image_path}", "-o", "{output_dir}", "-l", "{layers}"]
{segment_script}
"""
    print(f"🔍 Running depth segmentation on Windows (GPU)...")
    job_id = cli.run_async(cmd, timeout=300)
    status = cli.poll_job(job_id, interval=10, max_wait=300)
    
    if status.get("status") != "completed":
        print(f"❌ Segmentation failed: {status}")
        return None
    
    # 读取生成的layers.json
    result = cli.run_sync(f"""
import json
path = "{output_dir}/layers.json".replace("/", os.sep)
with open(path) as f:
    print(json.dumps(json.load(f)))
""", timeout=30)
    
    stdout = result.get("stdout", "")
    # 找到最后一行有效JSON
    for line in reversed(stdout.strip().split("\n")):
        line = line.strip()
        if line.startswith("["):
            return json.loads(line)
    
    print("❌ Failed to read layers.json")
    return None


def run_remote_render(layers, preset_name, camera="scroll_left", duration=6.0,
                      resolution=(1080, 1920), output_dir=WIN_OUTPUT_DIR):
    """在Windows端运行视差场景渲染"""
    sys.path.insert(0, ENGINE_CLIENT_DIR)
    from blender_client import BlenderAgentClient
    from generators.parallax import ParallaxParams, LayerConfig, generate_parallax_script

    cli = BlenderAgentClient(ENGINE_HOST)

    layer_configs = [
        LayerConfig(name=l["name"], image_path=l["image_path"], z_depth=l["z_depth"])
        for l in layers
    ]

    params = ParallaxParams(
        preset_name=preset_name,
        layers=layer_configs,
        camera_preset=camera,
        duration=duration,
        resolution=resolution,
        output_format="video",
        output_dir=output_dir,
    )

    script = generate_parallax_script(params)
    print(f"🎬 Rendering parallax scene...")
    job_id = cli.run_async(script, timeout=600)
    status = cli.poll_job(job_id, interval=10, max_wait=600)
    return status


def main():
    parser = argparse.ArgumentParser(description="2.5D视差场景全流程(Windows端)")
    parser.add_argument("--image-path", required=True, help="Windows端图片路径")
    parser.add_argument("--image-url", default=None, help="图片URL(自动下载到Windows)")
    parser.add_argument("-n", "--name", default="parallax_scene", help="输出文件名前缀")
    parser.add_argument("-o", "--output", default=WIN_OUTPUT_DIR, help="Windows端输出目录")
    parser.add_argument("-l", "--layers", type=int, default=3, choices=[2, 3, 4])
    parser.add_argument("--camera", default="scroll_left",
                        choices=["scroll_left", "scroll_right", "push_in", "dolly_zoom", "orbit", "static"])
    parser.add_argument("--duration", type=float, default=6.0)
    parser.add_argument("--ratio", default="9:16", choices=["9:16", "16:9", "1:1"])
    parser.add_argument("--engine-host", default=ENGINE_HOST)
    args = parser.parse_args()

    image_path = args.image_path
    output_dir = os.path.join(args.output, args.name)

    # Step 1: 深度分层 (Windows GPU)
    layers = run_remote_segment(image_path, output_dir, args.layers)
    if not layers:
        sys.exit(1)

    # Step 2: 视差渲染 (Windows GPU)
    resolution = {
        "9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)
    }[args.ratio]

    status = run_remote_render(
        layers, args.name,
        camera=args.camera, duration=args.duration,
        resolution=resolution, output_dir=output_dir,
    )

    if status.get("status") == "completed":
        print(f"\n🎉 完成!")
        print(f"  📁 {output_dir}")
        print(f"  🎬 {args.name}.mp4")
        print(f"  📄 {args.name}.blend")
    else:
        print(f"\n❌ 渲染失败: {status}")


if __name__ == "__main__":
    main()
