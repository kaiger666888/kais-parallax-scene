#!/usr/bin/env python3
"""
视差场景全流程编排
Linux端分层 → 传输到Windows → 通过kais-blender-engine渲染

用法:
  python3 parallax_pipeline.py wide_image.png --execute-remote
"""

import argparse
import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_CLIENT_DIR = os.path.expanduser("~/.openclaw/workspace/skills/kais-blender-engine/client")
ENGINE_HOST = "http://192.168.71.38:8080"
WIN_CACHE_DIR = "D:/BlenderAgent/cache/parallax"

# Z深度映射
LAYER_Z_MAP = {
    "foreground": -1.5,
    "midground": 0.0,
    "background": 7.5,
    "distant": 20.0,
}


def run_step(cmd, desc):
    """执行步骤"""
    print(f"\n{'='*50}")
    print(f"📋 {desc}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
    if result.returncode != 0:
        print(f"❌ {desc} 失败: {result.stderr[-300:]}")
        sys.exit(1)
    print(f"✅ {desc} 完成")
    return result


def transfer_to_windows(local_dir, remote_dir):
    """通过SSH传输分层文件到Windows"""
    os.makedirs(remote_dir, exist_ok=True)

    for f in os.listdir(local_dir):
        if not f.endswith(".png"):
            continue
        local_path = os.path.join(local_dir, f)
        remote_path = f"{remote_dir}/{f}"
        # Windows路径需要转换
        win_path = remote_path.replace("/", "\\")
        cmd = [
            "scp", "-i", os.path.expanduser("~/.ssh/id_windows"),
            local_path, f"kai@192.168.71.38:{win_path}"
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"  📤 {f} → {win_path}")


def render_remote(layers_json_path, args):
    """通过kais-blender-engine远程渲染"""
    sys.path.insert(0, ENGINE_CLIENT_DIR)

    from blender_client import BlenderAgentClient
    from generators.parallax import ParallaxParams, LayerConfig

    cli = BlenderAgentClient(args.engine_host)
    print(f"🔌 连接 {args.engine_host}...")
    print(f"   {cli.health()}")

    # 读取layers配置，替换为Windows路径
    with open(layers_json_path) as f:
        layers = json.load(f)

    layer_configs = []
    for layer in layers:
        win_path = os.path.join(WIN_CACHE_DIR, f"{layer['name']}.png").replace("/", "\\")
        layer_configs.append(LayerConfig(
            name=layer["name"],
            image_path=win_path,
            z_depth=layer["z_depth"],
        ))

    params = ParallaxParams(
        preset_name=args.name,
        layers=layer_configs,
        camera_preset=args.camera,
        duration=args.duration,
        resolution={
            "9:16": (1080, 1920),
            "16:9": (1920, 1080),
            "1:1": (1080, 1080),
        }[args.ratio],
        output_format="video" if args.render else "both",
        output_dir=WIN_CACHE_DIR.replace("/", "\\"),
    )

    script = generate_parallax_script(params)
    print("🚀 提交渲染任务...")
    result = cli.run_sync(script, timeout=600)
    print(f"状态: {result.get('status')}")
    return result


def main():
    parser = argparse.ArgumentParser(description="2.5D视差场景全流程")
    parser.add_argument("image", help="输入超宽图路径")
    parser.add_argument("-o", "--output", default=None, help="输出目录")
    parser.add_argument("-n", "--name", default="parallax_scene", help="输出文件名前缀")
    parser.add_argument("-l", "--layers", type=int, default=3, choices=[2, 3, 4])
    parser.add_argument("--camera", default="scroll_left",
                        choices=["scroll_left", "scroll_right", "push_in", "dolly_zoom", "orbit", "static"])
    parser.add_argument("--duration", type=float, default=6.0)
    parser.add_argument("--ratio", default="9:16", choices=["9:16", "16:9", "1:1"])
    parser.add_argument("--render", action="store_true", help="是否渲染视频")
    parser.add_argument("--manual-mask", default=None, help="手动蒙版路径")
    parser.add_argument("--execute-remote", action="store_true", help="传输到Windows并通过engine渲染")
    parser.add_argument("--engine-host", default=ENGINE_HOST, help="Blender Engine地址")
    args = parser.parse_args()

    image_path = os.path.abspath(args.image)
    if not os.path.exists(image_path):
        print(f"❌ 文件不存在: {image_path}")
        sys.exit(1)

    output_dir = args.output or os.path.join(os.path.dirname(image_path), "parallax_output")
    segments_dir = os.path.join(output_dir, "segments")
    os.makedirs(segments_dir, exist_ok=True)

    # Step 1: 深度估计 + 分层
    seg_cmd = [
        sys.executable, SCRIPT_DIR + "/depth_segment.py",
        image_path, "-o", segments_dir, "-l", str(args.layers)
    ]
    if args.manual_mask:
        seg_cmd.extend(["--manual-mask", args.manual_mask])
    run_step(" ".join(seg_cmd), "阶段一：智能分层")

    # Step 2: 远程渲染（可选）
    if args.execute_remote:
        layers_json = os.path.join(segments_dir, "layers.json")

        # 传输文件
        print(f"\n{'='*50}")
        print("📋 传输文件到Windows")
        transfer_to_windows(segments_dir, WIN_CACHE_DIR)

        # 渲染
        render_remote(layers_json, args)

    print(f"\n🎉 完成！输出目录: {output_dir}")


if __name__ == "__main__":
    main()
