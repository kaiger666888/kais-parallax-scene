#!/usr/bin/env python3
"""
视差场景全流程编排
输入：超宽图路径
输出：渲染视频 + .blend文件
"""

import argparse
import json
import os
import subprocess
import sys


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BLENDER_ENGINE_HOST = "http://192.168.71.38:8080"


def run_step(cmd, desc):
    """执行步骤，失败则终止"""
    print(f"\n{'='*60}")
    print(f"📋 {desc}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr and "warning" not in result.stderr.lower():
        print(f"STDERR: {result.stderr[:500]}")
    if result.returncode != 0:
        print(f"❌ {desc} 失败!")
        sys.exit(1)
    print(f"✅ {desc} 完成")
    return result


def main():
    parser = argparse.ArgumentParser(description="2.5D视差场景全流程")
    parser.add_argument("image", help="输入超宽图路径")
    parser.add_argument("-o", "--output", default=None, help="输出目录")
    parser.add_argument("-l", "--layers", type=int, default=3, choices=[2, 3, 4])
    parser.add_argument("--camera", default="scroll_left",
                        choices=["scroll_left", "scroll_right", "push_in", "dolly_zoom", "orbit", "static"])
    parser.add_argument("--duration", type=float, default=6.0)
    parser.add_argument("--ratio", default="9:16", choices=["9:16", "16:9", "1:1"])
    parser.add_argument("--render", action="store_true", help="是否渲染视频")
    parser.add_argument("--manual-mask", default=None, help="手动蒙版路径")
    parser.add_argument("--execute-remote", action="store_true", help="通过Blender Engine远程执行")
    args = parser.parse_args()

    image_path = os.path.abspath(args.image)
    if not os.path.exists(image_path):
        print(f"❌ 文件不存在: {image_path}")
        sys.exit(1)

    output_dir = args.output or os.path.join(os.path.dirname(image_path), "parallax_output")
    os.makedirs(output_dir, exist_ok=True)

    segments_dir = os.path.join(output_dir, "segments")
    render_path = os.path.join(output_dir, "output.mp4") if args.render else ""

    # Step 1: 深度估计 + 分层
    seg_cmd = [
        sys.executable, SCRIPT_DIR + "/depth_segment.py",
        image_path, "-o", segments_dir, "-l", str(args.layers)
    ]
    if args.manual_mask:
        seg_cmd.extend(["--manual-mask", args.manual_mask])
    run_step(" ".join(seg_cmd), "阶段一：智能分层")

    layers_json = os.path.join(segments_dir, "layers.json")
    if not os.path.exists(layers_json):
        print("❌ layers.json 未生成")
        sys.exit(1)

    # Step 2: 生成 Blender 脚本
    blend_cmd = [
        sys.executable, SCRIPT_DIR + "/generate_blend.py",
        layers_json,
        "-o", os.path.join(output_dir, "parallax_scene.py"),
        "--camera", args.camera,
        "--duration", str(args.duration),
        "--ratio", args.ratio,
    ]
    if render_path:
        blend_cmd.extend(["--render-path", render_path])
    run_step(" ".join(blend_cmd), "阶段二：生成Blender脚本")

    # Step 3: 远程执行（可选）
    if args.execute_remote:
        print(f"\n{'='*60}")
        print("📋 阶段三：远程渲染")
        print(f"{'='*60}")

        script_path = os.path.join(output_dir, "parallax_scene.py")
        try:
            import requests
            with open(script_path) as f:
                script_content = f.read()

            resp = requests.post(
                f"{BLENDER_ENGINE_HOST}/api/execute",
                json={"script": script_content},
                timeout=600
            )
            if resp.status_code == 200:
                result = resp.json()
                print(f"✅ 渲染完成: {result.get('outputs', [])}")
            else:
                print(f"❌ 远程执行失败: {resp.status_code} {resp.text}")
        except ImportError:
            print("⚠️  需要安装 requests: pip install requests")
        except Exception as e:
            print(f"❌ 远程执行错误: {e}")

    print(f"\n🎉 全流程完成！输出目录: {output_dir}")
    print(f"  📁 segments/   - 分层PNG")
    print(f"  📄 parallax_scene.py - Blender脚本")
    if args.render:
        print(f"  🎬 output.mp4  - 渲染视频")


if __name__ == "__main__":
    main()
