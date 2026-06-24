"""build_character.py — COMPONENT 1 of the studio: turn a raw model + a recipe into a reusable,
validated character ASSET (baked .blend + preview.png + resolved recipe).

ONE file, TWO modes (it detects which python it's in):

  * LAUNCHER (run with the skill45video python — it has pyyaml):
        python build_character.py characters/riya/character.yaml [--inspect]
    Parses the YAML recipe, writes a JSON spec, drives Blender headless to bake, then writes the
    resolved recipe. With --inspect it opens the baked .blend in the Blender GUI afterwards (QA).

  * BAKE (Blender's python, invoked by the launcher as `... -- --bake <spec.json>`):
        import the source model -> detect rig -> normalize (height + feet on floor) -> paint
        clothing -> validate -> save characters/<name>/character.blend + preview.png + resolved JSON.

How an AI uses it: write/edit characters/<name>/character.yaml, run the launcher, then read the
validation report + preview.png and self-correct (height / forward / colors) — a headless loop.
"""
import json
import os
import sys


def _argv_after_dashdash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


try:
    import bpy  # noqa: F401  (present only inside Blender)
    HAVE_BPY = True
except Exception:
    HAVE_BPY = False

BAKE = HAVE_BPY and "--bake" in _argv_after_dashdash()


# ============================================================ BAKE (Blender python)
def render_preview(meshes, out_png, forward="+Y", res=720):
    """Render a PNG of the built character so NK / an AI can eyeball it. The camera sits on the side
    the character FACES (per `forward`) so we see the front, with a soft key+fill. Runs AFTER the asset
    .blend is saved, so these preview lights/camera don't pollute the saved asset."""
    import math

    import bpy
    from mathutils import Vector

    from studiolib import world_bbox
    mins, maxs = world_bbox(meshes)
    center = (mins + maxs) * 0.5
    size = maxs - mins
    back = max(size.x, size.y, size.z, 0.5) * 2.0 + 0.8

    world = bpy.data.worlds.new("preview")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (0.16, 0.18, 0.22, 1)   # neutral studio grey
        bg.inputs["Strength"].default_value = 1.0

    # camera on the FORWARD side (so we see the face), slightly to one side + above
    fw = str(forward).strip()
    off = {"+Y": (0.30, 1.0), "-Y": (0.30, -1.0), "+X": (1.0, 0.30), "-X": (-1.0, 0.30)}.get(fw, (0.30, 1.0))
    cd = bpy.data.cameras.new("pcam")
    cd.lens = 50
    cam = bpy.data.objects.new("pcam", cd)
    bpy.context.collection.objects.link(cam)
    cam.location = (center.x + off[0] * back, center.y + off[1] * back, center.z + size.z * 0.12)
    look = Vector((center.x, center.y, center.z))
    cam.rotation_euler = (look - cam.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam

    # key (sun from camera-ish side) + softer fill area light from the other side
    key = bpy.data.lights.new("key", "SUN")
    key.energy = 3.5
    ko = bpy.data.objects.new("key", key)
    bpy.context.collection.objects.link(ko)
    ko.location = cam.location
    ko.rotation_euler = (math.radians(55), 0, math.radians(25))
    fill = bpy.data.lights.new("fill", "AREA")
    fill.energy = 60.0
    fill.size = 4.0
    fo = bpy.data.objects.new("fill", fill)
    bpy.context.collection.objects.link(fo)
    fo.location = (center.x - off[0] * back, center.y + off[1] * back * 0.6, center.z + size.z * 0.5)
    fo.rotation_euler = (look - fo.location).to_track_quat("-Z", "Y").to_euler()

    sc = bpy.context.scene
    try:
        sc.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = os.path.abspath(out_png)
    sc.frame_set(1)
    bpy.ops.render.render(write_still=True)
    print(f"[char] preview ({fw}-facing) -> {out_png}")


def bake(spec_path):
    import math

    import bpy
    from mathutils import Vector

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from studiolib import (attach_garment, clothe_body, detect_rig, feet_to_origin, find_armature,
                           height_scale, format_report, import_model, recolor_meshes, save_blend,
                           validate_character, world_bbox)

    spec = json.loads(open(spec_path, encoding="utf-8").read())
    name = spec["name"]
    target = float(spec.get("target_height", 1.7))
    look = spec.get("look", {})

    bpy.ops.wm.read_factory_settings(use_empty=True)
    body_objs = import_model(spec["source"])
    body_arm = find_armature(body_objs)
    body_meshes = [o for o in body_objs if o.type == "MESH"]
    rig = detect_rig(body_arm) if body_arm else {"scheme": "?", "bones": 0, "map": {}}
    print(f"[char] rig: scheme={rig['scheme']} bones={rig['bones']}")

    # --- optional garment outfit: a mesh skinned to the SAME rig, fitted to the body (scale-matched)
    garment_meshes, garment_arm = [], None
    garment_path = look.get("garment")
    if garment_path and body_arm:
        garment_meshes, garment_arm = attach_garment(body_arm, import_model(garment_path),
                                                     oversize=float(look.get("garment_oversize", 1.0)))
    elif garment_path:
        print("[char] WARNING garment requested but body has no armature — skipping garment")

    # --- normalize: park body roots (+ the garment's armature) under a named root empty, scale to the
    #     BODY's target height, orient forward, feet at z=0
    mins, maxs = world_bbox(body_meshes) if body_meshes else (Vector((0, 0, 0)), Vector((1, 1, target)))
    measured = max(maxs.z - mins.z, 1e-4)
    scale = height_scale(measured, target)
    roots = [o for o in body_objs if o.parent is None] + ([garment_arm] if garment_arm else [])
    root = bpy.data.objects.new(f"CHAR_{name}", None)
    bpy.context.collection.objects.link(root)
    for r in roots:
        r.parent = root
        r.matrix_parent_inverse = root.matrix_world.inverted()
    root.scale = (scale, scale, scale)
    yaw = {"+Y": 0, "-Y": 180, "+X": -90, "-X": 90}.get(str(spec.get("forward", "+Y")).strip(), 0)
    root.rotation_euler = (0.0, 0.0, math.radians(yaw))
    bpy.context.view_layer.update()
    feet_to_origin(root, body_meshes + garment_meshes)
    print(f"[char] normalize: measured={measured:.3f} -> scale={scale:.4f} target={target} forward={spec.get('forward','+Y')}")

    # --- materials:
    #   garment   -> keep the garment's own materials; recolor the body to skin (exposed face/arms/legs)
    #   textured  -> keep everything (clothed/textured source like Mixamo/VRoid)
    #   painted   -> paint skin/shirt/lower regions on the nude body
    skin = tuple(look.get("skin", [0.80, 0.62, 0.50]))
    if look.get("textured"):
        print("[char] textured source — keeping original materials (no paint)")
    elif garment_meshes:
        recolor_meshes(body_meshes, skin)
        print("[char] garment outfit — body recolored to skin, garment keeps its own materials")
    else:
        clothes = look.get("clothes")
        if not (clothes and body_arm and clothe_body(body_meshes, body_arm, clothes.get("kind", "casual"), skin,
                                                     tuple(clothes.get("shirt", [0.94, 0.94, 0.97])),
                                                     tuple(clothes.get("lower", [0.16, 0.18, 0.38])),
                                                     float(clothes.get("baggy", 0.0)))):
            recolor_meshes(body_meshes, skin)

    # --- validate (measure, don't eyeball) — height from the body
    bpy.context.view_layer.update()
    report = validate_character(body_arm, body_meshes, target)
    print(format_report(report))

    # --- collect the character into its own collection (clean to append later)
    char_objs = body_objs + garment_meshes + ([garment_arm] if garment_arm else [])
    coll = bpy.data.collections.new(f"char_{name}")
    bpy.context.scene.collection.children.link(coll)
    for o in [root] + char_objs:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        coll.objects.link(o)

    # --- save the asset, then render a preview (preview lights are added post-save, not baked in)
    save_blend(spec["out_blend"])
    try:
        render_preview(body_meshes + garment_meshes, spec["out_preview"], forward=spec.get("forward", "+Y"))
    except Exception as e:
        print(f"[char] preview skipped ({e})")

    resolved = {"measured_height": round(measured, 4), "applied_scale": round(scale, 4),
                "rig": rig["scheme"], "bones": rig["bones"], "bone_map": rig["map"],
                "validation": {"ok": report["ok"], "critical_fail": report["critical_fail"],
                               "checks": [[n, bool(ok), d] for n, ok, d in report["checks"]]}}
    with open(spec["out_resolved"], "w", encoding="utf-8") as fh:
        json.dump(resolved, fh, ensure_ascii=False, indent=2)
    print(f"[char] resolved -> {spec['out_resolved']}")
    if report["critical_fail"]:
        raise SystemExit("[char] CRITICAL validation failure (no rig or no mesh) — check the source model")


# ============================================================ LAUNCHER (skill45video python)
def launcher():
    import argparse
    import subprocess
    from pathlib import Path

    import yaml

    here = Path(__file__).resolve().parent
    assets = here / "assets"
    blender = Path(os.environ.get("SKILL45_BLENDER")
                   or r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe")

    ap = argparse.ArgumentParser()
    ap.add_argument("recipe", help="path to characters/<name>/character.yaml")
    ap.add_argument("--inspect", action="store_true",
                    help="open the baked .blend in the Blender GUI after building (QA)")
    a = ap.parse_args()

    recipe_path = Path(a.recipe).resolve()
    recipe = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    name = recipe.get("name") or recipe_path.parent.name
    outdir = recipe_path.parent
    source = recipe["source"]
    source_abs = source if os.path.isabs(source) else str((assets / source).resolve())
    if not os.path.exists(source_abs):
        raise SystemExit(f"[build_character] source not found: {source_abs}")

    look = dict(recipe.get("look", {}))
    garment = look.get("garment")     # resolve a garment-mesh path under assets/ to absolute
    if garment:
        garment_abs = garment if os.path.isabs(garment) else str((assets / garment).resolve())
        if not os.path.exists(garment_abs):
            raise SystemExit(f"[build_character] garment not found: {garment_abs}")
        look["garment"] = garment_abs

    spec = {
        "name": name,
        "source": source_abs,
        "target_height": recipe.get("target_height", 1.7),
        "forward": recipe.get("forward", "+Y"),
        "bone_map": recipe.get("bone_map"),
        "look": look,
        "out_blend": str(outdir / "character.blend"),
        "out_preview": str(outdir / "preview.png"),
        "out_resolved": str(outdir / "character.resolved.json"),
    }
    spec_path = outdir / "_build.spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[build_character] {name}: baking from {Path(source_abs).name} ...", flush=True)
    rc = subprocess.run([str(blender), "--background", "--python", str(Path(__file__).resolve()),
                         "--", "--bake", str(spec_path)]).returncode
    if rc != 0:
        raise SystemExit(f"[build_character] bake failed (rc={rc})")

    resolved = json.loads((outdir / "character.resolved.json").read_text(encoding="utf-8"))
    merged = dict(recipe)
    merged["bone_map"] = resolved.get("bone_map")
    merged["measured_height"] = resolved.get("measured_height")
    merged["built"] = {"blend": "character.blend", "preview": "preview.png",
                       "rig": resolved.get("rig"), "bones": resolved.get("bones"),
                       "validation_ok": resolved["validation"]["ok"]}
    (outdir / "character.resolved.yaml").write_text(
        yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding="utf-8")

    print(f"\n[build_character] done -> {outdir}")
    print("  character.blend          (baked: normalized + clothed; renderer links this)")
    print("  preview.png              (eyeball it)")
    print("  character.resolved.yaml  (detected bone_map + measured height)")
    print(f"  validation OK = {resolved['validation']['ok']}"
          f"{'  (CRITICAL FAIL)' if resolved['validation']['critical_fail'] else ''}")
    for n, ok, d in resolved["validation"]["checks"]:
        print(f"    [{'PASS' if ok else 'FAIL'}] {n:14s} {d}")

    if a.inspect:
        print("\n[build_character] opening Blender GUI on the baked character (close it when done) ...")
        subprocess.run([str(blender), str(outdir / "character.blend")])


if __name__ == "__main__":
    if BAKE:
        a = _argv_after_dashdash()
        bake(a[a.index("--bake") + 1])
    elif HAVE_BPY:
        print("build_character: nothing to do inside Blender without --bake. "
              "Run the launcher with the skill45video python: python build_character.py <recipe.yaml>")
    else:
        launcher()
