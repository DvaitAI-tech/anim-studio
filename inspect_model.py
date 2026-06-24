"""Inspect 3D files: report rig (armature/bones + canonical bone map), animation, mesh size, bbox.
Run: blender --background --python inspect_model.py -- <file1> <file2> ...
"""
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from studiolib import detect_rig

argv = sys.argv
paths = argv[argv.index("--") + 1:] if "--" in argv else []


def imp(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path, automatic_bone_orientation=True)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".vrm":
        bpy.ops.import_scene.vrm(filepath=path)   # needs the VRM Add-on for Blender
    else:
        raise SystemExit(f"unsupported: {ext}")


for path in paths:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    print("\n" + "=" * 60)
    print(f"FILE: {path}")
    try:
        imp(path)
    except Exception as e:
        print(f"  IMPORT FAILED: {type(e).__name__}: {e}")
        continue
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    bones = []
    for a in arms:
        bones += [b.name for b in a.data.bones]
    has_anim = any(o.animation_data and o.animation_data.action for o in bpy.data.objects)
    verts = sum(len(m.data.vertices) for m in meshes)

    # bbox
    mins = Vector((1e9, 1e9, 1e9)); maxs = Vector((-1e9, -1e9, -1e9))
    for m in meshes:
        for c in m.bound_box:
            w = m.matrix_world @ Vector(c)
            mins = Vector((min(mins[i], w[i]) for i in range(3)))
            maxs = Vector((max(maxs[i], w[i]) for i in range(3)))
    size = maxs - mins if meshes else Vector((0, 0, 0))

    # per-mesh dimensions (find the odd one out, e.g. a stray giant sphere)
    print("  per-mesh (name: dims x,y,z | verts):")
    for m in meshes:
        mlo = Vector((1e9, 1e9, 1e9)); mhi = Vector((-1e9, -1e9, -1e9))
        for c in m.bound_box:
            w = m.matrix_world @ Vector(c)
            mlo = Vector((min(mlo[i], w[i]) for i in range(3)))
            mhi = Vector((max(mhi[i], w[i]) for i in range(3)))
        d = mhi - mlo
        print(f"    {m.name}: ({d.x:.2f}, {d.y:.2f}, {d.z:.2f}) | {len(m.data.vertices)}v")

    mixamo = any("mixamorig" in b.lower() for b in bones)
    actions = [a.name for a in bpy.data.actions]
    print(f"  meshes={len(meshes)} verts={verts}")
    print(f"  armatures={len(arms)}  bones={len(bones)}  mixamorig={mixamo}")
    print(f"  has_animation={has_anim}")
    print(f"  size (x,y,z) = ({size.x:.2f}, {size.y:.2f}, {size.z:.2f})")
    print(f"  RIGGED={'YES' if arms and bones else 'NO'}")
    if bones:
        print(f"  sample bones: {bones[:10]}")
    if arms:
        rig = detect_rig(arms[0])
        print(f"  rig scheme: {rig['scheme']}  canonical map: {rig['map']}")
    print(f"  ACTIONS ({len(actions)}): {actions[:40]}")
