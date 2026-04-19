"""
高层API封装 —— 一行代码调用视差场景管线
"""

import os
import sys
import json
import subprocess


class ParallaxClient:
    """2.5D视差场景生成客户端"""

    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    ENGINE_HOST = "http://192.168.71.38:8080"

    def __init__(self, engine_host=None):
        if engine_host:
            self.ENGINE_HOST = engine_host

    def create_parallax(
        self,
        image_path: str,
        output_dir: str = None,
        layers: int = 3,
        camera_preset: str = "scroll_left",
        duration: float = 6.0,
        output_ratio: str = "9:16",
        render: bool = False,
        execute_remote: bool = False,
        manual_mask: str = None,
    ) -> dict:
        """
        完整视差场景管线

        Args:
            image_path: 超宽图路径
            output_dir: 输出目录
            layers: 分层数 (2-4)
            camera_preset: scroll_left/right, push_in, dolly_zoom, orbit, static
            duration: 动画时长(秒)
            output_ratio: 9:16, 16:9, 1:1
            render: 是否渲染视频
            execute_remote: 是否通过Blender Engine远程执行
            manual_mask: 手动蒙版路径

        Returns:
            dict: {"segments_dir", "script_path", "layers_config", "render_output"}
        """
        image_path = os.path.abspath(image_path)
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        output_dir = output_dir or os.path.join(
            os.path.dirname(image_path), "parallax_output"
        )
        os.makedirs(output_dir, exist_ok=True)

        segments_dir = os.path.join(output_dir, "segments")

        # Step 1: 分层
        self._run_depth_segment(image_path, segments_dir, layers, manual_mask)

        # Step 2: 生成Blender脚本
        layers_json = os.path.join(segments_dir, "layers.json")
        script_path = os.path.join(output_dir, "parallax_scene.py")
        render_path = os.path.join(output_dir, "output.mp4") if render else ""

        self._run_generate_blend(
            layers_json, script_path, camera_preset, duration, output_ratio, render_path
        )

        # Step 3: 远程执行
        render_output = None
        if execute_remote and render:
            render_output = self._execute_remote(script_path)

        # 读取layers配置
        with open(layers_json) as f:
            layers_config = json.load(f)

        return {
            "segments_dir": segments_dir,
            "script_path": script_path,
            "layers_config": layers_config,
            "render_output": render_output,
            "output_dir": output_dir,
        }

    def _run_depth_segment(self, image, output, layers, mask):
        cmd = [
            sys.executable, self.SCRIPT_DIR + "/../scripts/depth_segment.py",
            image, "-o", output, "-l", str(layers)
        ]
        if mask:
            cmd.extend(["--manual-mask", mask])
        subprocess.run(cmd, check=True)

    def _run_generate_blend(self, layers_json, output, camera, duration, ratio, render_path):
        cmd = [
            sys.executable, self.SCRIPT_DIR + "/../scripts/generate_blend.py",
            layers_json, "-o", output,
            "--camera", camera, "--duration", str(duration), "--ratio", ratio
        ]
        if render_path:
            cmd.extend(["--render-path", render_path])
        subprocess.run(cmd, check=True)

    def _execute_remote(self, script_path):
        try:
            import requests
            with open(script_path) as f:
                script = f.read()
            resp = requests.post(
                f"{self.ENGINE_HOST}/api/execute",
                json={"script": script},
                timeout=600
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            raise RuntimeError(f"Remote execution failed: {e}")
