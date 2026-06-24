"""Armature / rig helpers: find the armature, build a canonical bone map, bind actions
(Blender 4.4+ slotted-action fix), and normalize clip timing.

The canonical bone_map lets the rest of the studio reason about a body in role terms
(pelvis, spine, head, thigh_l...) regardless of the rig's naming scheme (Quaternius
'Standard' vs Mixamo 'mixamorig...').
"""
import bpy

# canonical role -> ordered name-substring candidates (first match wins; shortest name per sub)
BONE_ROLES = {
    "pelvis":  ["pelvis", "hips", "hip"],
    "spine":   ["spine_03", "spine_02", "chest", "spine_01", "spine"],
    "neck":    ["neck"],
    "head":    ["head"],
    "thigh_l": ["thigh_l", "upperleg_l", "leftupleg"],
    "thigh_r": ["thigh_r", "upperleg_r", "rightupleg"],
    "calf_l":  ["calf_l", "shin_l", "lowerleg_l", "knee_l", "leftleg"],
    "foot_l":  ["foot_l", "ankle_l", "leftfoot"],
}


def find_armature(objects):
    for o in objects:
        if o.type == "ARMATURE":
            return o
    return None


def find_bone(arm, *subs):
    """First bone whose name contains one of `subs` (case-insensitive); shortest name wins per sub."""
    names = [b.name for b in arm.data.bones]
    for sub in subs:
        cands = [n for n in names if sub.lower() in n.lower()]
        if cands:
            return sorted(cands, key=len)[0]
    return None


def bone_map(arm):
    """Resolve canonical roles -> actual bone names for this armature (value None if a role is missing)."""
    return {role: find_bone(arm, *subs) for role, subs in BONE_ROLES.items()}


def detect_rig(arm):
    """Report the rig: scheme guess, bone count, mixamo flag, and the canonical bone_map.
    Returns {scheme, bones, mixamo, map}."""
    names = [b.name for b in arm.data.bones]
    mixamo = any("mixamorig" in n.lower() for n in names)
    return {"scheme": "mixamo" if mixamo else "standard",
            "bones": len(names), "mixamo": mixamo, "map": bone_map(arm)}


def bone_z_world(arm, name):
    """Rest-pose world Z of a bone head (head_local, so pose-independent). None if name is falsy/missing."""
    if not name:
        return None
    b = arm.data.bones.get(name)
    return (arm.matrix_world @ b.head_local).z if b else None


def bind_action(arm, action):
    """Assign an action AND bind its slot. Blender 4.4+ 'slotted actions' require action_slot to be
    set or the channels never apply — this was the cause of the frozen/T-pose characters."""
    if not arm.animation_data:
        arm.animation_data_create()
    arm.animation_data.action = action
    slots = list(getattr(action, "slots", []))
    if slots:
        obj_slots = [s for s in slots if getattr(s, "target_id_type", "OBJECT") == "OBJECT"]
        try:
            arm.animation_data.action_slot = (obj_slots or slots)[0]
        except Exception as e:
            print(f"   [rig] slot bind failed: {e}")


def shift_action_to_frame1(action):
    """Move an action's keyframes so it starts at frame 1. Multi-take libraries (Quaternius packs all
    43 clips on one shared timeline) leave each imported clip at a high offset; rendering frames 1..N
    would land before the clip and show a frozen pose. Idempotent (guarded by a custom prop)."""
    if action.get("_shifted_to_1"):
        return
    fr = action.frame_range
    off = fr[0] - 1.0
    if abs(off) > 0.5:
        for fc in action.fcurves:
            for kp in fc.keyframe_points:
                kp.co.x -= off
                kp.handle_left.x -= off
                kp.handle_right.x -= off
            fc.update()
    action["_shifted_to_1"] = True
