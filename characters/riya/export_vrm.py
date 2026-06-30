"""Export a .blend character to a .vrm using the VRM Add-on for Blender's Python API.

Refs the addon scripting API: https://vrm-addon-for-blender.info/en-us/scripting-api/
  import:  bpy.ops.import_scene.vrm(filepath=...)
  export:  bpy.ops.export_scene.vrm(filepath=...)
  humanoid (VRM1): armature.data.vrm_addon_extension.vrm1.humanoid.human_bones.<bone>.node.bone_name = "..."

RUN WITH BLENDER (headless):
  & "C:\\Program Files\\Blender Foundation\\Blender 4.5\\blender.exe" --background `
      --python characters/riya/export_vrm.py -- --blend characters/riya/character.blend `
      --out characters/riya/riya.vrm

What it does: open the .blend, find the armature, map its bones to the VRM humanoid (auto-operator
first, manual name-matching fallback), then export a .vrm.

HONEST LIMIT: this exports the BODY + skeleton as a valid VRM, but it canNOT create facial
blendshapes/visemes — the addon API has no such function, and a Quaternius body has none. So the
result renders a visible character but has NO mouth/expression shapes for lip-sync. For talking
faces you still need a character that already ships visemes (a real VRoid Studio export).
"""
import argparse
import os
import sys

import bpy

# anim-studio root on sys.path so we can reuse studiolib (addon-enable + bone finding)
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from studiolib.blendio import _ensure_vrm_addon  # noqa: E402
from studiolib.rig import find_armature, find_bone  # noqa: E402

# VRM humanoid role -> candidate bone-name substrings (case-insensitive; covers Quaternius + Mixamo).
HUMAN_BONES = {
    "hips":          ["hips", "pelvis", "hip"],
    "spine":         ["spine_01", "spine1", "spine"],
    "chest":         ["spine_02", "chest", "spine2"],
    "upperChest":    ["spine_03", "upperchest", "spine3"],
    "neck":          ["neck"],
    "head":          ["head"],
    "leftShoulder":  ["shoulder_l", "clavicle_l", "leftshoulder"],
    "leftUpperArm":  ["upperarm_l", "upper_arm_l", "leftarm"],
    "leftLowerArm":  ["lowerarm_l", "forearm_l", "lower_arm_l", "leftforearm"],
    "leftHand":      ["hand_l", "lefthand"],
    "rightShoulder": ["shoulder_r", "clavicle_r", "rightshoulder"],
    "rightUpperArm": ["upperarm_r", "upper_arm_r", "rightarm"],
    "rightLowerArm": ["lowerarm_r", "forearm_r", "lower_arm_r", "rightforearm"],
    "rightHand":     ["hand_r", "righthand"],
    "leftUpperLeg":  ["thigh_l", "upperleg_l", "upper_leg_l", "leftupleg"],
    "leftLowerLeg":  ["calf_l", "shin_l", "lowerleg_l", "lower_leg_l", "leftleg"],
    "leftFoot":      ["foot_l", "ankle_l", "leftfoot"],
    "leftToes":      ["toe_l", "toebase_l", "ball_l", "lefttoebase"],
    "rightUpperLeg": ["thigh_r", "upperleg_r", "upper_leg_r", "rightupleg"],
    "rightLowerLeg": ["calf_r", "shin_r", "lowerleg_r", "lower_leg_r", "rightleg"],
    "rightFoot":     ["foot_r", "ankle_r", "rightfoot"],
    "rightToes":     ["toe_r", "toebase_r", "ball_r", "righttoebase"],
}


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--blend", default=os.path.join(here, "character.blend"),
                    help="source .blend to export (default: character.blend beside this script)")
    ap.add_argument("--out", default=None, help="output .vrm (default: <blend stem>.vrm beside it)")
    return ap.parse_args(argv)


def _try_auto_assign(arm):
    """Try the addon's auto humanoid-bone assignment operators. Arg name varies by version, so try
    a few signatures (and no-arg, since we set the armature active)."""
    for opid in ("assign_vrm1_humanoid_human_bones_automatically",
                 "assign_vrm0_humanoid_human_bones_automatically"):
        op = getattr(bpy.ops.vrm, opid, None)
        if op is None:
            continue
        for kw in ({}, {"armature_object_name": arm.name}, {"armature_name": arm.name}):
            try:
                op(**kw)
                print(f"[vrm] auto humanoid assign via vrm.{opid}({list(kw)})")
                return True
            except Exception as e:                           # noqa: BLE001
                last = f"{type(e).__name__}: {e}"
        print(f"[vrm] vrm.{opid} failed: {last}")
    return False


def _manual_assign(arm):
    """Map bones to VRM1 human_bones by name. Tolerant of attribute-name differences across versions."""
    hb = arm.data.vrm_addon_extension.vrm1.humanoid.human_bones
    mapped = 0
    for role, subs in HUMAN_BONES.items():
        bone = find_bone(arm, *subs)
        if not bone:
            continue
        # addon attr is the role in lowerCamel (e.g. leftUpperArm); also try snake_case just in case
        target = getattr(hb, role, None)
        if target is None:
            snake = "".join("_" + c.lower() if c.isupper() else c for c in role)
            target = getattr(hb, snake, None)
        if target is not None:
            try:
                target.node.bone_name = bone
                mapped += 1
            except Exception as e:                           # noqa: BLE001
                print(f"[vrm] could not set {role} -> {bone}: {e}")
    print(f"[vrm] manually mapped {mapped}/{len(HUMAN_BONES)} humanoid bones")
    return mapped


def main():
    a = parse_args()
    blend = os.path.abspath(a.blend)
    out = os.path.abspath(a.out or os.path.splitext(blend)[0] + ".vrm")
    if not os.path.exists(blend):
        raise SystemExit(f"[error] blend not found: {blend}")

    _ensure_vrm_addon()
    bpy.ops.wm.open_mainfile(filepath=blend)
    arm = find_armature(list(bpy.data.objects))
    if not arm:
        raise SystemExit("[error] no armature in the blend — VRM needs a humanoid rig")
    print(f"[vrm] armature='{arm.name}' bones={len(arm.data.bones)}")
    print("[vrm] bone names: " + ", ".join(b.name for b in arm.data.bones))

    # ensure it's the active/selected object (export operates on the armature's hierarchy)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)

    if not _try_auto_assign(arm):
        _manual_assign(arm)

    res = bpy.ops.export_scene.vrm(filepath=out)
    if res != {"FINISHED"}:
        raise SystemExit(f"[error] VRM export did not finish: {res}")
    size = os.path.getsize(out) if os.path.exists(out) else 0
    print(f"[vrm] EXPORTED -> {out} ({size} bytes)")
    print("[vrm] NOTE: body+skeleton only; no facial blendshapes (API can't create them).")


if __name__ == "__main__":
    main()
