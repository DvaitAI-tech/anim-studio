"""Validation checks for a built character — turn 'looks fine' into measurable pass/fail.

`validate_character` returns a report the build tool prints and an AI can read to self-correct.
`tpose_check` is the trick that cracked the slotted-action bug: bind an action and confirm a pose
bone actually moves across two frames, instead of trusting the eye.
"""
import bpy

from .geometry import world_bbox
from .rig import bind_action, bone_map, detect_rig


def validate_character(arm, meshes, target_height, tol=0.15):
    """Run sanity checks; return {ok, critical_fail, checks:[(name, ok, detail)]}.
    critical_fail = missing rig or mesh (can't be a usable character); other fails are warnings."""
    checks = []

    has_rig = arm is not None
    checks.append(("rig_present", has_rig, arm.name if arm else "no armature"))

    rig = detect_rig(arm) if arm else {"map": {}, "scheme": "?"}
    core = ["pelvis", "spine", "head", "thigh_l", "thigh_r"]
    missing = [r for r in core if not rig["map"].get(r)]
    checks.append(("bone_map", not missing,
                   f"missing={missing}" if missing else f"scheme={rig.get('scheme')}"))

    mins, maxs = world_bbox(meshes)
    h = maxs.z - mins.z
    checks.append(("height", abs(h - target_height) <= tol, f"{h:.3f}m (target {target_height})"))
    checks.append(("feet_on_floor", abs(mins.z) <= tol, f"min.z={mins.z:.3f}"))

    has_mesh = len(meshes) > 0
    checks.append(("has_mesh", has_mesh, f"{len(meshes)} mesh(es)"))

    critical_fail = not (has_rig and has_mesh)
    ok = all(c[1] for c in checks)
    return {"ok": ok, "critical_fail": critical_fail, "checks": checks}


def tpose_check(arm, action):
    """Bind `action` and confirm a leg bone actually rotates between frame 1 and 8 (the slotted-action
    trick). Returns (moved, detail). Use when the source model ships its own clip."""
    if not arm or not action:
        return False, "no arm/action to test"
    leg = bone_map(arm).get("thigh_l")
    pb = arm.pose.bones.get(leg) if leg else (arm.pose.bones[0] if len(arm.pose.bones) else None)
    if not pb:
        return False, "no pose bone"
    bind_action(arm, action)
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    q1 = pb.matrix.to_quaternion()
    bpy.context.scene.frame_set(8)
    bpy.context.view_layer.update()
    q2 = pb.matrix.to_quaternion()
    d = (q1 - q2).length
    return d > 1e-4, f"|dq|={d:.4f} on {pb.name}"


def format_report(report):
    """Pretty multi-line string of a validate_character report."""
    lines = [f"  validation: {'OK' if report['ok'] else 'WARN'}"
             f"{' / CRITICAL' if report['critical_fail'] else ''}"]
    for name, ok, detail in report["checks"]:
        lines.append(f"    [{'PASS' if ok else 'FAIL'}] {name:14s} {detail}")
    return "\n".join(lines)
