#!/usr/bin/env python3
"""
生成 Blender Python 脚本 —— 将分层PNG构建为视差场景
输入：layers.json（由depth_segment.py生成）
输出：Blender可执行的Python脚本
"""

import argparse
import json
import os


BLENDER_TEMPLATE = '''
import bpy
import os
import math

# ====== 配置 ======
LAYERS = {layers_json}
CAMERA_PRESET = "{camera_preset}"
DURATION = {duration}
FOCAL_LENGTH = {focal_length}
OUTPUT_RATIO = "{output_ratio}"
RENDER_PATH = "{render_path}"

# ====== 清理场景 ======
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

# ====== 创建摄像机 ======
cam_data = bpy.data.cameras.new("ParallaxCam")
cam_data.lens = FOCAL_LENGTH
cam_data.sensor_fit = 'AUTO'
cam_obj = bpy.data.objects.new("Camera", cam_data)
bpy.context.scene.collection.objects.link(cam_obj)
bpy.context.scene.camera = cam_obj

# ====== 设置输出分辨率 ======
scene = bpy.context.scene
if OUTPUT_RATIO == "9:16":
    scene.render.resolution_x = 1080
    scene.render.resolution_y = 1920
elif OUTPUT_RATIO == "16:9":
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
elif OUTPUT_RATIO == "1:1":
    scene.render.resolution_x = 1080
    scene.render.resolution_y = 1080
scene.render.engine = 'BLENDER_EEVEE_NEXT'
scene.render.fps = 24
scene.frame_end = int(DURATION * 24)

# ====== 创建分层平面 ======
for layer in LAYERS:
    name = layer["name"]
    z = layer["z_depth"]
    img_path = layer["image_path"]
    
    # 计算缩放补偿
    scale = 1.0 + (abs(z) / FOCAL_LENGTH)
    
    # 创建Plane
    bpy.ops.mesh.primitive_plane_add(size=20.0, location=(0, z, 0))
    plane = bpy.context.active_object
    plane.name = f"Layer_{name}"
    plane.scale = (scale, 1.0, 1.0)
    
    # 加载纹理
    if os.path.exists(img_path):
        mat = bpy.data.materials.new(name=f"Mat_{name}")
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes["Principled BSDF"]
        
        tex_node = mat.node_tree.nodes.new('ShaderNodeTexImage')
        tex_node.image = bpy.data.images.load(img_path)
        tex_node.image.colorspace_settings.name = 'sRGB'
        
        # Alpha混合
        mat.blend_method = 'BLEND'
        mat.node_tree.links.new(tex_node.outputs['Color'], bsdf.inputs['Base Color'])
        mat.node_tree.links.new(tex_node.outputs['Alpha'], bsdf.inputs['Alpha'])
        
        plane.data.materials.append(mat)
    else:
        print(f"WARNING: Texture not found: {{img_path}}")

# ====== 摄像机动画 ======
cam = bpy.data.objects["Camera"]

if CAMERA_PRESET == "scroll_left":
    # 横向平移（左→右），缓入缓出
    cam.location = (-3.0, -2.0, 0.0)
    cam.keyframe_insert(data_path="location", frame=1)
    
    cam.location = (3.0, -2.0, 0.0)
    cam.keyframe_insert(data_path="location", frame=scene.frame_end)
    
    # F-Curve 缓入缓出
    for fc in cam.animation_data.action.fcurves:
        for kf in fc.keyframe_points:
            kf.interpolation = 'BEZIER'
            kf.handle_left_type = 'AUTO_CLAMPED'
            kf.handle_right_type = 'AUTO_CLAMPED'

elif CAMERA_PRESET == "scroll_right":
    cam.location = (3.0, -2.0, 0.0)
    cam.keyframe_insert(data_path="location", frame=1)
    cam.location = (-3.0, -2.0, 0.0)
    cam.keyframe_insert(data_path="location", frame=scene.frame_end)

elif CAMERA_PRESET == "push_in":
    cam.location = (0.0, -5.0, 0.0)
    cam.keyframe_insert(data_path="location", frame=1)
    cam.location = (0.0, -2.0, 0.0)
    cam.keyframe_insert(data_path="location", frame=scene.frame_end)

elif CAMERA_PRESET == "dolly_zoom":
    # 推轨变焦（Vertigo效果）
    cam.location = (0.0, -5.0, 0.0)
    cam.keyframe_insert(data_path="location", frame=1)
    cam.location = (0.0, -1.5, 0.0)
    cam.keyframe_insert(data_path="location", frame=scene.frame_end)
    # 同时缩小焦距
    cam_data = cam.data
    cam_data.lens = 85.0
    cam_data.keyframe_insert(data_path="lens", frame=1)
    cam_data.lens = 24.0
    cam_data.keyframe_insert(data_path="lens", frame=scene.frame_end)

elif CAMERA_PRESET == "orbit":
    import math
    frames = scene.frame_end
    for i in range(1, frames + 1):
        angle = (i / frames) * math.pi / 2  # 90度
        r = 5.0
        cam.location = (r * math.sin(angle), r * math.cos(angle), 1.0)
        cam.keyframe_insert(data_path="location", frame=i)
        # 朝向原点
        direction = -cam.location
        rot_y = math.atan2(direction.x, direction.y)
        cam.rotation_euler = (0, 0, rot_y)
        cam.keyframe_insert(data_path="rotation_euler", frame=i)

elif CAMERA_PRESET == "static":
    cam.location = (0.0, -2.0, 0.0)
    # 无动画

# ====== 灯光 ======
light_data = bpy.data.lights.new(name="ParallaxLight", type='SUN')
light_data.energy = 2.0
light_obj = bpy.data.objects.new("SunLight", light_data)
light_obj.location = (0, 0, 10)
light_obj.rotation_euler = (0, 0, 0)
bpy.context.scene.collection.objects.link(light_obj)

# ====== 渲染 ======
if RENDER_PATH:
    os.makedirs(os.path.dirname(RENDER_PATH), exist_ok=True)
    scene.render.filepath = RENDER_PATH
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'
    bpy.ops.render.render(animation=True)
    print(f"✅ 渲染完成: {{RENDER_PATH}}")

print("🎉 Parallax scene setup complete!")
'''


def generate_script(layers_json_path, output_script_path, **kwargs):
    """生成 Blender Python 脚本"""
    with open(layers_json_path) as f:
        layers = json.load(f)

    script = BLENDER_TEMPLATE.format(
        layers_json=json.dumps(layers, indent=4, ensure_ascii=False),
        camera_preset=kwargs.get("camera_preset", "scroll_left"),
        duration=kwargs.get("duration", 6.0),
        focal_length=kwargs.get("focal_length", 35),
        output_ratio=kwargs.get("output_ratio", "9:16"),
        render_path=kwargs.get("render_path", ""),
    )

    with open(output_script_path, "w") as f:
        f.write(script)

    print(f"✅ Blender脚本生成: {output_script_path}")
    return output_script_path


def main():
    parser = argparse.ArgumentParser(description="生成Blender视差场景脚本")
    parser.add_argument("layers_json", help="layers.json路径")
    parser.add_argument("-o", "--output", default=None, help="输出脚本路径")
    parser.add_argument("--camera", default="scroll_left",
                        choices=["scroll_left", "scroll_right", "push_in", "dolly_zoom", "orbit", "static"])
    parser.add_argument("--duration", type=float, default=6.0)
    parser.add_argument("--ratio", default="9:16", choices=["9:16", "16:9", "1:1"])
    parser.add_argument("--focal-length", type=float, default=35.0)
    parser.add_argument("--render-path", default="", help="渲染输出路径（留空则不渲染）")
    args = parser.parse_args()

    output_path = args.output or os.path.join(os.path.dirname(args.layers_json), "parallax_scene.py")

    generate_script(
        args.layers_json,
        output_path,
        camera_preset=args.camera,
        duration=args.duration,
        focal_length=args.focal_length,
        output_ratio=args.ratio,
        render_path=args.render_path,
    )


if __name__ == "__main__":
    main()
