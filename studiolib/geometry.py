"""Geometry & spatial math for the studio (Blender-python side; uses mathutils).

Pure helpers shared by the renderer and the character builder. The only ones with side
effects translate an object and say so in their name (e.g. feet_to_origin).
"""
import math

import bpy
from mathutils import Vector


def world_bbox(objects):
    """Combined world-space AABB of all MESH objects -> (mins, maxs).
    Falls back to a ~human-sized box when there are no meshes."""
    mins = Vector((1e9, 1e9, 1e9))
    maxs = Vector((-1e9, -1e9, -1e9))
    found = False
    for o in objects:
        if o.type != "MESH":
            continue
        found = True
        for corner in o.bound_box:
            wc = o.matrix_world @ Vector(corner)
            mins = Vector((min(mins[i], wc[i]) for i in range(3)))
            maxs = Vector((max(maxs[i], wc[i]) for i in range(3)))
    if not found:
        return Vector((0, 0, 0)), Vector((1, 1, 2))  # sane default for a ~human
    return mins, maxs


def center_dims(objects):
    """(center, size) of the world bbox: center=(mins+maxs)/2, size=maxs-mins."""
    mins, maxs = world_bbox(objects)
    return (mins + maxs) * 0.5, (maxs - mins)


def height_scale(measured_h, target_h=1.7):
    """Uniform scale to bring a model of height `measured_h` to `target_h` (= target/measured).
    Mixamo FBX often imports ~100x too big; this normalizes it."""
    return target_h / max(measured_h, 1e-4)


def angle_to_face(dx, dy):
    """Z-rotation (degrees) so a +Y-forward character faces direction (dx, dy).
    Convention: local +Y is forward; face=180 looks toward camera (-Y). = degrees(atan2(-dx, dy))."""
    return math.degrees(math.atan2(-dx, dy))


def feet_to_origin(root_obj, objects):
    """Translate `root_obj` so the lowest mesh point sits at z=0 (feet on the floor).
    Returns the z offset that was removed."""
    bpy.context.view_layer.update()
    mins, _ = world_bbox(objects)
    root_obj.location.z -= mins.z
    bpy.context.view_layer.update()
    return mins.z
