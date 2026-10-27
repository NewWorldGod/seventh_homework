# -*- coding: utf-8 -*-
"""Build the white-model demo scene used by the depth-control experiment.

Run headless:
    blender -b -P blender/make_demo_scene.py -- --out assets/demo_white_model.blend --res 512

The scene contains a clay-looking sphere, torus, bevelled cube and cylinder on
a ground plane, a three-point area-light rig and a 63 mm camera, so that a
depth map rendered from it has several distinct depth layers and clean
occlusion boundaries.
"""
from __future__ import annotations

import argparse
import math
import os
import sys

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="assets/demo_white_model.blend")
    p.add_argument("--res", type=int, default=512)
    p.add_argument("--samples", type=int, default=64)
    return p.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def matte(name: str, color, roughness: float) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = 0.0
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.25
    elif "Specular" in bsdf.inputs:
        bsdf.inputs["Specular"].default_value = 0.25
    return mat


def look_at(obj: bpy.types.Object, target) -> None:
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def add_area(name: str, location, energy: float, size: float, target) -> None:
    light = bpy.data.lights.new(name, type="AREA")
    light.energy = energy
    light.shape = "DISK"
    light.size = size
    obj = bpy.data.objects.new(name, light)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    look_at(obj, target)


def add_mesh(primitive: str, location, material: bpy.types.Material, **kwargs) -> bpy.types.Object:
    getattr(bpy.ops.mesh, primitive)(location=location, **kwargs)
    obj = bpy.context.active_object
    obj.data.materials.append(material)
    return obj


def main() -> int:
    args = parse_args()
    clear_scene()

    clay = matte("clay_white", (0.78, 0.78, 0.80), 0.65)
    ground_mat = matte("ground_grey", (0.20, 0.20, 0.22), 0.55)

    # Ground
    bpy.ops.mesh.primitive_plane_add(size=40.0, location=(0.0, 0.0, 0.0))
    ground = bpy.context.active_object
    ground.name = "ground"
    ground.data.materials.append(ground_mat)

    # Sphere (front left)
    sphere = add_mesh(
        "primitive_uv_sphere_add",
        (-1.75, 0.35, 0.95),
        clay,
        radius=0.95,
        segments=64,
        ring_count=32,
    )
    sphere.name = "sphere"
    bpy.ops.object.shade_smooth()

    # Torus standing upright, slightly tilted (centre)
    bpy.ops.mesh.primitive_torus_add(
        location=(0.05, 0.15, 1.15),
        major_radius=0.95,
        minor_radius=0.32,
        major_segments=64,
        minor_segments=24,
        rotation=(math.radians(78.0), 0.0, math.radians(-12.0)),
    )
    torus = bpy.context.active_object
    torus.name = "torus"
    torus.data.materials.append(clay)
    bpy.ops.object.shade_smooth()

    # Bevelled cube (right)
    cube = add_mesh(
        "primitive_cube_add",
        (1.90, 0.65, 0.78),
        clay,
        size=1.55,
        rotation=(0.0, 0.0, math.radians(22.0)),
    )
    cube.name = "cube_beveled"
    bevel = cube.modifiers.new("bevel", "BEVEL")
    bevel.width = 0.11
    bevel.segments = 5
    bevel.limit_method = "ANGLE"

    # Cylinder (back right, partially behind the cube)
    cyl = add_mesh(
        "primitive_cylinder_add",
        (2.15, 1.55, 0.92),
        clay,
        radius=0.52,
        depth=1.84,
        vertices=64,
    )
    cyl.name = "cylinder"
    bpy.ops.object.shade_smooth()

    # Small sphere half hidden behind the torus: gives an occlusion case
    bpy.ops.mesh.primitive_uv_sphere_add(
        location=(-0.35, 1.75, 0.42), radius=0.42, segments=48, ring_count=24
    )
    small = bpy.context.active_object
    small.name = "sphere_small"
    small.data.materials.append(clay)
    bpy.ops.object.shade_smooth()

    # Camera: 63 mm, framed on the object group
    cam_data = bpy.data.cameras.new("camera_63mm")
    cam_data.lens = 63.0
    cam_data.sensor_width = 36.0
    cam = bpy.data.objects.new("camera_63mm", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = Vector((0.0, -12.8, 4.3))
    look_at(cam, (0.15, 0.40, 1.05))
    bpy.context.scene.camera = cam

    # Three-point lighting
    add_area("key_light", (-4.5, -5.5, 6.5), 900.0, 4.0, (0.0, 0.3, 1.1))
    add_area("fill_light", (5.5, -4.0, 3.2), 260.0, 6.0, (0.0, 0.4, 0.9))
    add_area("rim_light", (2.5, 5.5, 5.5), 750.0, 3.0, (0.0, 0.5, 1.2))

    # Soft ambient so unlit sides keep some tone
    world = bpy.data.worlds.new("studio_world")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.38, 0.40, 0.44, 1.0)
    bg.inputs["Strength"].default_value = 0.45
    bpy.context.scene.world = world

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = True
    scene.cycles.max_bounces = 6
    scene.cycles.diffuse_bounces = 3
    scene.cycles.glossy_bounces = 3
    scene.cycles.transmission_bounces = 2
    scene.render.resolution_x = args.res
    scene.render.resolution_y = args.res
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out)
    print(f"[make_demo_scene] saved {out}  res={args.res}  samples={args.samples}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
