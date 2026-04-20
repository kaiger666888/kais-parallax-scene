#!/usr/bin/env python3
"""
AI视差场景生成管线 — 三步法

步骤1: 即梦文生图 → 原始场景
步骤2: 即梦图生图 → 超宽背景(21:9) + 前景(白色背景)
步骤3: rembg抠图 + 视差合成 → MP4

用法:
  python ai_parallax_pipeline.py --prompt "A cozy coffee shop..." --output out.mp4
  python ai_parallax_pipeline.py --prompt "咖啡店内部" --duration 4 --bg-ratio 21:9
"""

import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np
import requests
from PIL import Image


# ─── 即梦 API ──────────────────────────────────────

class JimengAPI:
    """即梦免费API客户端（基于jimeng-free-api容器）"""

    def __init__(self, base_url="http://localhost:8000", session_id=""):
        self.base_url = base_url
        self.session_id = session_id

    def generate_image(self, prompt, model="jimeng-5.0", ratio="16:9", resolution="2k",
                       ref_images=None, seed=None, timeout=120):
        """文生图或图生图"""
        body = {"model": model, "prompt": prompt, "ratio": ratio, "resolution": resolution}
        if ref_images:
            body["images"] = ref_images
        if seed is not None:
            body["seed"] = seed

        resp = requests.post(
            f"{self.base_url}/v1/images/generations",
            headers={
                "Authorization": f"Bearer {self.session_id}",
                "Content-Type": "application/json"
            },
            json=body,
            timeout=timeout,
        )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            print(f"⏳ 限流，等待 {retry_after}s...")
            time.sleep(retry_after)
            return self.generate_image(prompt, model, ratio, resolution, ref_images, seed, timeout)

        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])

    def download(self, url, output_path):
        """下载图片"""
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(r.content)
        return output_path


# ─── 合成引擎 ──────────────────────────────────────

def remove_background(input_path, output_path):
    """使用rembg去除前景白色背景"""
    from rembg import remove
    img = Image.open(input_path)
    result = remove(img)
    result.save(output_path)
    return output_path


def composite_parallax(bg_path, fg_path, output_path, duration=3.0, fps=24,
                       fg_shift=30, bg_shift_ratio=0.6):
    """Ken Burns + 前景视差偏移合成"""
    bg = np.array(Image.open(bg_path).convert("RGBA"))
    fg = np.array(Image.open(fg_path).convert("RGBA"))
    h, w = fg.shape[:2]

    # 缩放背景到前景高度
    bg_h, bg_w = bg.shape[:2]
    scale = h / bg_h
    bg_w_scaled = int(bg_w * scale)
    bg_scaled = np.array(Image.fromarray(bg).resize((bg_w_scaled, h), Image.LANCZOS))

    # 预放大前景
    fg_zoom = 1.1
    fg_w = int(w * fg_zoom)
    fg_h = int(h * fg_zoom)
    pre_fg = np.array(Image.fromarray(fg).resize((fg_w, fg_h), Image.LANCZOS))

    max_pan_bg = (bg_w_scaled - w) // 2
    max_pan_fg = (fg_w - w) // 2

    frames_dir = output_path.rsplit(".", 1)[0] + "_frames"
    os.makedirs(frames_dir, exist_ok=True)

    frames = int(duration * fps)

    for i in range(frames):
        t = (i / (frames - 1)) - 0.5

        # 背景：Ken Burns微动
        pan_bg = int(max_pan_bg * t * bg_shift_ratio)
        cx = bg_w_scaled // 2 + pan_bg
        x1 = max(0, cx - w // 2)
        canvas = bg_scaled[:, x1:x1 + w].copy()

        # 前景：视差偏移
        pan_fg = int(max_pan_fg * t * 0.8)
        cx_fg = fg_w // 2 + pan_fg
        x1f = max(0, cx_fg - w // 2)
        fg_frame = pre_fg[(fg_h - h) // 2:(fg_h + h) // 2, x1f:x1f + w].copy()

        # alpha叠加
        a = fg_frame[:, :, 3].astype(np.float32) / 255.0
        for c in range(3):
            canvas[:, :, c] = np.clip(
                a * fg_frame[:, :, c] + (1 - a) * canvas[:, :, c], 0, 255
            ).astype(np.uint8)
        canvas[:, :, 3] = np.clip(
            a * 255 + (1 - a) * canvas[:, :, 3], 0, 255
        ).astype(np.uint8)

        Image.fromarray(canvas).save(f"{frames_dir}/{i + 1:04d}.png")

    # ffmpeg
    r = subprocess.run(
        f'ffmpeg -y -framerate {fps} -i "{frames_dir}/%04d.png" '
        f'-c:v libx264 -pix_fmt yuv420p -crf 18 "{output_path}"',
        shell=True, capture_output=True, text=True
    )
    if os.path.exists(output_path):
        return output_path
    else:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-300:]}")


# ─── 主管线 ──────────────────────────────────────

def _upload_for_ref(local_path):
    """上传图片到临时HTTP服务，返回URL供即梦图生图使用。
    
    如果图片已是URL则直接返回。
    如果本地有jimeng-free-api容器，使用其代理能力。
    否则使用base64 data URI。
    """
    if local_path.startswith("http"):
        return local_path
    # 即梦API支持base64 data URI
    import base64
    mime = "image/png" if local_path.endswith(".png") else "image/jpeg"
    with open(local_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f"data:{mime};base64,{b64}"


def run_pipeline(prompt, output_path, session_id,
                 model="jimeng-5.0", bg_ratio="21:9", fg_ratio="16:9",
                 resolution="2k", duration=3.0, fps=24,
                 jimeng_base_url="http://localhost:8000",
                 work_dir="/tmp/jimeng_parallax",
                 source_image=None):
    """三步AI视差管线"""
    os.makedirs(work_dir, exist_ok=True)

    api = JimengAPI(jimeng_base_url, session_id)

    # ── 步骤1: 获取原始场景图（用户图 or 文生图） ──
    if source_image and os.path.exists(source_image):
        print("📷 步骤1: 使用用户提供的原始图...")
        orig_path = f"{work_dir}/step1_original.png"
        # 复制到工作目录
        Image.open(source_image).save(orig_path)
        # 上传到可访问的URL（即梦图生图需要URL）
        orig_url = _upload_for_ref(orig_path)
        print(f"   ✅ 用户图: {source_image}")
    else:
        print("🎨 步骤1: 文生图...")
        step1 = api.generate_image(prompt, model=model, ratio="16:9", resolution=resolution)
        if not step1:
            raise RuntimeError("文生图失败")
        orig_url = step1[0]["url"]
        orig_path = f"{work_dir}/step1_original.png"
        api.download(orig_url, orig_path)
        print(f"   ✅ 原始场景: {orig_path}")
        time.sleep(1.5)  # QPS安全

    # ── 步骤2a: 图生图 - 超宽背景 ──
    print("🖼️  步骤2a: 图生图 - 超宽背景...")
    bg_prompt = (
        f"{prompt}, background only, no people no furniture, "
        "empty interior, walls shelves decorations, "
        "wide panoramic view, photorealistic, 8k, same style as reference"
    )
    step2 = api.generate_image(bg_prompt, model=model, ratio=bg_ratio,
                                resolution=resolution, ref_images=[orig_url])
    if not step2:
        raise RuntimeError("背景图生成失败")
    bg_url = step2[0]["url"]
    bg_path = f"{work_dir}/step2_background.png"
    api.download(bg_url, bg_path)
    print(f"   ✅ 超宽背景({bg_ratio}): {bg_path}")

    time.sleep(1.5)

    # ── 步骤2b: 图生图 - 前景 ──
    print("🖼️  步骤2b: 图生图 - 前景...")
    fg_prompt = (
        f"{prompt}, foreground subjects only, people sitting, "
        "furniture tables chairs, isolated on white background, "
        "cutout style, photorealistic, 8k, same style as reference"
    )
    step3 = api.generate_image(fg_prompt, model=model, ratio=fg_ratio,
                                resolution=resolution, ref_images=[orig_url])
    if not step3:
        raise RuntimeError("前景图生成失败")
    fg_url = step3[0]["url"]
    fg_raw_path = f"{work_dir}/step3_foreground_raw.png"
    api.download(fg_url, fg_raw_path)
    print(f"   ✅ 前景({fg_ratio}): {fg_raw_path}")

    # ── 步骤3: rembg抠图 + 视差合成 ──
    print("✂️  步骤3a: rembg去除前景背景...")
    fg_clean_path = f"{work_dir}/step3_foreground_clean.png"
    remove_background(fg_raw_path, fg_clean_path)
    print(f"   ✅ 抠图完成: {fg_clean_path}")

    print("🎬 步骤3b: 视差合成...")
    video = composite_parallax(bg_path, fg_clean_path, output_path,
                               duration=duration, fps=fps)
    size = os.path.getsize(video)
    print(f"\n🎉 完成: {video} ({size / 1024:.0f}KB, {duration}s)")

    return {
        "original": orig_path,
        "background": bg_path,
        "foreground_raw": fg_raw_path,
        "foreground_clean": fg_clean_path,
        "video": video,
    }


def main():
    parser = argparse.ArgumentParser(description="AI视差场景生成管线（三步法）")
    parser.add_argument("--prompt", required=False, help="场景描述（有--source-image时可选）")
    parser.add_argument("--source-image", default=None, help="用户提供的原始图路径（跳过文生图）")
    parser.add_argument("-o", "--output", default="output.mp4", help="输出MP4路径")
    parser.add_argument("--session-id", default="", help="即梦session ID（或设JIMENG_SESSION_ID环境变量）")
    parser.add_argument("--model", default="jimeng-5.0", help="即梦模型")
    parser.add_argument("--bg-ratio", default="21:9", help="背景图比例（21:9更宽）")
    parser.add_argument("--fg-ratio", default="16:9", help="前景图比例")
    parser.add_argument("--resolution", default="2k", help="分辨率（1k/2k）")
    parser.add_argument("--duration", type=float, default=3.0, help="视频时长(秒)")
    parser.add_argument("--fps", type=int, default=24, help="帧率")
    parser.add_argument("--work-dir", default="/tmp/jimeng_parallax", help="工作目录")
    parser.add_argument("--jimeng-url", default="http://localhost:8000", help="即梦API地址")
    args = parser.parse_args()

    session_id = args.session_id or os.environ.get("JIMENG_SESSION_ID", "")
    if not session_id:
        try:
            result = subprocess.run(
                "docker exec jimeng-free-api printenv JIMENG_SESSION_ID",
                shell=True, capture_output=True, text=True, timeout=5
            )
            session_id = result.stdout.strip()
        except Exception:
            pass
    if not session_id:
        print("❌ 需要即梦session ID: --session-id 或 JIMENG_SESSION_ID 环境变量")
        sys.exit(1)

    if not args.prompt and not args.source_image:
        print("❌ 需要 --prompt 或 --source-image")
        sys.exit(1)

    run_pipeline(
        prompt=args.prompt or "",
        output_path=args.output,
        session_id=session_id,
        model=args.model,
        bg_ratio=args.bg_ratio,
        fg_ratio=args.fg_ratio,
        resolution=args.resolution,
        duration=args.duration,
        fps=args.fps,
        jimeng_base_url=args.jimeng_url,
        work_dir=args.work_dir,
        source_image=args.source_image,
    )


if __name__ == "__main__":
    main()
