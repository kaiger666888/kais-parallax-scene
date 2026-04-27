#!/usr/bin/env python3
"""
Parallax Scene Generation API Server

FastAPI wrapper for kais-parallax-scene, compatible with kais-hub ToolAdapter.

Endpoints:
  GET  /health   — Health check
  POST /submit   — Submit a parallax generation or depth segmentation task
  POST /status   — Poll task status
"""

import asyncio
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel


# Thread pool for blocking GPU work
_executor = ThreadPoolExecutor(max_workers=1)

# In-memory task store
_tasks: dict[str, dict[str, Any]] = {}

SCRIPT_DIR = Path(__file__).resolve().parent


class SubmitRequest(BaseModel):
    task_type: str = "generate"  # generate | segment
    prompt: str = ""
    source_image_path: str | None = None
    output_dir: str | None = None
    mode: str = "auto"
    num_layers: int = 3
    duration: float = 3.0
    fps: int = 24
    parallax_strength: int = 200
    kenburns_zoom: float = 1.1
    kenburns_pan: int = 80
    resolution: str = "16:9"
    edge_sigma: float = 3.0


class StatusRequest(BaseModel):
    job_id: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    _executor.shutdown(wait=False)


app = FastAPI(title="Parallax Scene Generator", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/submit")
def submit(req: SubmitRequest):
    job_id = str(uuid.uuid4())[:8]
    _tasks[job_id] = {"status": "running", "output_files": [], "error": ""}

    if req.task_type == "segment":
        _executor.submit(_run_segment, job_id, req)
    else:
        _executor.submit(_run_generate, job_id, req)

    return {"status": "accepted", "job_id": job_id}


@app.post("/status")
def status(req: StatusRequest):
    task = _tasks.get(req.job_id)
    if not task:
        return {"status": "failed", "error": "Unknown job_id"}
    return task


def _run_segment(job_id: str, req: SubmitRequest):
    """Run depth segmentation in background thread."""
    import subprocess
    import sys

    try:
        output_dir = req.output_dir or f"/tmp/parallax_segments/{job_id}"
        cmd = [
            sys.executable, str(SCRIPT_DIR / "depth_segment.py"),
            req.source_image_path or "",
            "-o", output_dir,
            "-l", str(req.num_layers),
            "--sigma", str(req.edge_sigma),
        ]
        cmd = [c for c in cmd if c]  # Remove empty args

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            _tasks[job_id] = {"status": "failed", "error": result.stderr[-500:]}
            return

        output_path = Path(output_dir)
        files = [str(f.relative_to(output_path)) for f in output_path.rglob("*") if f.is_file()]
        _tasks[job_id] = {"status": "done", "output_files": files}

    except Exception as e:
        _tasks[job_id] = {"status": "failed", "error": str(e)}


def _run_generate(job_id: str, req: SubmitRequest):
    """Run full parallax pipeline in background thread."""
    import subprocess
    import sys

    try:
        output_dir = req.output_dir or f"/tmp/parallax_output/{job_id}"
        segments_dir = f"{output_dir}/segments"
        video_path = f"{output_dir}/output.mp4"

        # Step 1: Depth segmentation
        cmd = [
            sys.executable, str(SCRIPT_DIR / "depth_segment.py"),
            req.source_image_path or "",
            "-o", segments_dir,
            "-l", str(req.num_layers),
            "--sigma", str(req.edge_sigma),
        ]
        cmd = [c for c in cmd if c]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            _tasks[job_id] = {"status": "failed", "error": f"Segment failed: {result.stderr[-300:]}"}
            return

        # Step 2: Composite
        resolution_map = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}
        w, h = resolution_map.get(req.resolution, (1920, 1080))

        cmd = [
            sys.executable, str(SCRIPT_DIR / "parallax_composite.py"),
            "--image-dir", segments_dir,
            "-o", video_path,
            "--mode", req.mode,
            "--duration", str(req.duration),
            "--fps", str(req.fps),
            "--parallax-strength", str(req.parallax_strength),
            "--kenburns-zoom", str(req.kenburns_zoom),
            "--kenburns-pan", str(req.kenburns_pan),
            "--width", str(w),
            "--height", str(h),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            _tasks[job_id] = {"status": "failed", "error": f"Composite failed: {result.stderr[-300:]}"}
            return

        output_path = Path(output_dir)
        files = [str(f.relative_to(output_path)) for f in output_path.rglob("*") if f.is_file()]
        _tasks[job_id] = {"status": "done", "output_files": files}

    except Exception as e:
        _tasks[job_id] = {"status": "failed", "error": str(e)}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)
