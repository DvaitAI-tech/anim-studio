"""Wardrobe: put a garment mesh onto a body's armature — a real, swappable 'change clothes' system.

The garment FBX is skinned to the SAME skeleton as the body (e.g. Quaternius Modular Outfits share the
Universal rig: matching bone names + vertex groups). So dressing the body = point the garment mesh's
Armature modifier at the body armature and drop the garment's own armature. No re-weighting, no sculpting,
no retargeting. This is the only clothing approach an agent can drive reliably.
"""
import bpy

from .rig import find_armature


_JUNK_NAMES = ("icosphere", "sphere", "cube", "plane", "light", "camera", "empty", "proxy")


def _armature_span(arm):
    """World-space size of an armature = max extent of its bone heads. Captures BOTH a baked unit
    difference (FBX cm vs glTF m) and any object scale — the thing we need to match between two rigs."""
    bpy.context.view_layer.update()
    pts = [arm.matrix_world @ b.head_local for b in arm.data.bones]
    if not pts:
        return 0.0
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    zs = [p.z for p in pts]
    return max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def attach_garment(body_arm, garment_objs, oversize=1.0):
    """Fit a garment (skinned to the SAME skeleton as the body) onto the body, regardless of export-scale
    mismatch. THE MATH: align the garment's armature to the body's via their shared root bone (matches
    position + orientation + scale), then apply `oversize` (>1 = roomier, so the garment sits over the
    body instead of clipping). We KEEP the garment's own armature — at render time it gets the SAME action
    as the body, so identical rigs + identical motion means the clothes track the body exactly. Drops junk
    (the 2 m 'Icosphere' Quaternius ships) + empties. Returns (garment_meshes, garment_armature)."""
    g_arm = find_armature(garment_objs)
    meshes = [o for o in garment_objs if o.type == "MESH"
              and len(o.vertex_groups) > 0
              and not any(j in o.name.lower() for j in _JUNK_NAMES)]
    skipped = [o.name for o in garment_objs if o.type == "MESH" and o not in meshes]
    if skipped:
        print(f"   [wardrobe] skipped non-garment meshes: {skipped}")
    if not (g_arm and meshes):
        print("   [wardrobe] no skinned garment armature/mesh found; dropping import")
        for o in list(garment_objs):
            try:
                bpy.data.objects.remove(o, do_unlink=True)
            except Exception:
                pass
        return [], None

    # ALIGN the garment armature so its ROOT bone coincides with the body's root bone — this matches
    # position + orientation + scale in one shot, fixing export-axis differences (glTF Y-up vs FBX) and
    # unit-scale mismatches. (g_arm is unparented here, so setting matrix_world is direct.)
    root_name = next((n for n in ("root", "pelvis", "hips")
                      if body_arm.data.bones.get(n) and g_arm.data.bones.get(n)), None)
    if root_name:
        wb = body_arm.matrix_world @ body_arm.data.bones[root_name].matrix_local
        g_arm.matrix_world = wb @ g_arm.data.bones[root_name].matrix_local.inverted()
        print(f"   [wardrobe] aligned garment to body via '{root_name}' bone ({len(meshes)} mesh(es))")
    else:
        sb, sg = _armature_span(body_arm), _armature_span(g_arm)
        ratio = (sb / sg) if sg > 1e-9 else 1.0
        g_arm.scale = (g_arm.scale.x * ratio, g_arm.scale.y * ratio, g_arm.scale.z * ratio)
        g_arm.location = body_arm.location.copy()
        g_arm.rotation_euler = body_arm.rotation_euler.copy()
        print(f"   [wardrobe] no shared root bone — fell back to span scale x{ratio:.3f}")
    if oversize and abs(oversize - 1.0) > 1e-6:           # widen girth (X/Y) only — NOT height (Z)
        g_arm.scale = (g_arm.scale.x * oversize, g_arm.scale.y * oversize, g_arm.scale.z)
        print(f"   [wardrobe] oversize x{oversize} (width/depth only, height unchanged)")
    bpy.context.view_layer.update()

    keep = set(meshes) | {g_arm}                         # drop junk meshes + empties; keep garment rig+meshes
    for o in list(garment_objs):
        if o not in keep:
            try:
                bpy.data.objects.remove(o, do_unlink=True)
            except Exception:
                pass
    return meshes, g_arm
