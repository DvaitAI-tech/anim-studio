"""anim-studio — headless Blender renderer.

Two modes (run with Blender's bundled python, no pip deps):
  * shot-mode  (M1+): `--shot spec.json`  — multi-character scene shot written by build_scene.py
  * model-mode (M0):   `--model file`      — render one rigged model's own animation, dual aspect

Shared geometry/rig/mesh/io helpers live in `studiolib/` (imported below); this file keeps the
scene-assembly + render orchestration. Lip-sync is a later milestone (M3). Audio is muxed by ffmpeg
in build_scene.py, so this stays pure-Blender.

  & "C:\\Program Files\\Blender Foundation\\Blender 4.5\\blender.exe" --background `
      --python render_blender.py -- --model assets/characters/CesiumMan.glb --aspect 16x9 --out out/proof
"""
import argparse
import json
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from studiolib import (append_character, bind_action, clothe_body, colored_mat, find_armature,
                       import_model, recolor_meshes, shift_action_to_frame1, world_bbox)
from studiolib.geometry import angle_to_face


# ---------------------------------------------------------------- args
def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot", help="shot-mode: path to a shot-spec JSON (M1). Overrides single-model args.")
    ap.add_argument("--model", help="single-model mode (M0): path to a rigged .glb/.gltf/.fbx")
    ap.add_argument("--aspect", default="16x9", choices=["16x9", "9x16"])
    ap.add_argument("--seconds", type=float, default=6.0, help="max clip length")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--out", default="out/proof", help="output path stem (aspect+.mp4 appended)")
    ap.add_argument("--engine", default="eevee", choices=["eevee", "cycles"])
    ap.add_argument("--samples", type=int, default=64)
    return ap.parse_args(argv)


# ---------------------------------------------------------------- scene helpers
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def enable_gpu():
    """Prefer OptiX (RTX hardware RT), fall back to CUDA. Only affects Cycles."""
    prefs = bpy.context.preferences.addons["cycles"].preferences
    chosen = None
    for ctype in ("OPTIX", "CUDA"):
        try:
            prefs.compute_device_type = ctype
            chosen = ctype
            break
        except TypeError:
            continue
    prefs.refresh_devices()
    on = []
    for d in prefs.devices:
        d.use = d.type in ("OPTIX", "CUDA")
        if d.use:
            on.append(d.name)
    print(f"[gpu] compute_device_type={chosen} enabled={on}")
    return chosen


def animation_range(objects, fps, seconds):
    """Frame range from the first armature's action, capped to `seconds`."""
    start, end = 1, int(seconds * fps)
    for o in objects:
        ad = getattr(o, "animation_data", None)
        if ad and ad.action:
            fr = ad.action.frame_range
            start = int(fr[0])
            end = min(int(fr[1]), start + int(seconds * fps))
            print(f"[anim] action '{ad.action.name}' frames {int(fr[0])}-{int(fr[1])} "
                  f"-> render {start}-{end}")
            return start, end
    print(f"[anim] no action found; rendering static {start}-{end}")
    return start, end


def add_floor(center, size, color=(0.04, 0.04, 0.05)):
    radius = max(size.x, size.y) * 4 + 2
    bpy.ops.mesh.primitive_plane_add(size=radius, location=(center.x, center.y, 0))
    floor = bpy.context.active_object
    mat = bpy.data.materials.new("floor")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color, 1)
        bsdf.inputs["Roughness"].default_value = 0.85
    floor.data.materials.append(mat)


def set_world_hdri(path, strength=1.0):
    """Use an HDRI image as the world: realistic sky/backdrop + image-based lighting in one."""
    world = bpy.data.worlds.new("studio")
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    bg = nt.nodes.new("ShaderNodeBackground")
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    out = nt.nodes.new("ShaderNodeOutputWorld")
    try:
        env.image = bpy.data.images.load(path)
    except Exception as e:
        print(f"   [hdri] FAILED to load {path}: {e} — falling back to flat world")
        return set_world_color()
    bg.inputs["Strength"].default_value = strength
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    print(f"   [hdri] world = {os.path.basename(path)} (strength {strength})")


def set_world_color(rgb=(0.02, 0.02, 0.03)):
    world = bpy.data.worlds.new("studio")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs["Color"].default_value = (*rgb, 1)
        bg.inputs["Strength"].default_value = 0.4


def add_light(name, loc, energy, kind="AREA", size=5.0):
    data = bpy.data.lights.new(name, type=kind)
    data.energy = energy
    if kind == "AREA":
        data.size = size
    obj = bpy.data.objects.new(name, data)
    obj.location = loc
    bpy.context.collection.objects.link(obj)
    return obj


def aim(obj, target):
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def add_three_point(center, size):
    h = size.z
    d = max(size.x, size.y, size.z) * 2.5 + 2
    key = add_light("key", (center.x + d * 0.6, center.y - d, center.z + h), 1200, "AREA", 6)
    fill = add_light("fill", (center.x - d, center.y - d * 0.5, center.z + h * 0.6), 400, "AREA", 8)
    rim = add_light("rim", (center.x, center.y + d, center.z + h * 1.4), 800, "AREA", 4)
    for l in (key, fill, rim):
        aim(l, center)


def add_camera(center, size, aspect):
    """3/4 front camera framed to fit the subject for the chosen aspect."""
    maxdim = max(size.x, size.y, size.z)
    # 9:16 is tall+narrow -> pull back a touch less (height fills easily); 16:9 wider -> more back-off
    back = maxdim * (2.4 if aspect == "16x9" else 2.7) + 1.5
    eye_h = center.z + size.z * 0.15
    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 50  # natural ~portrait look
    cam = bpy.data.objects.new("cam", cam_data)
    cam.location = (center.x + back * 0.45, center.y - back, eye_h)
    bpy.context.collection.objects.link(cam)
    aim(cam, Vector((center.x, center.y, center.z + size.z * 0.05)))
    bpy.context.scene.camera = cam
    return cam


def configure_render(args):
    scene = bpy.context.scene
    if args.aspect == "16x9":
        scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    else:
        scene.render.resolution_x, scene.render.resolution_y = 1080, 1920
    scene.render.fps = args.fps

    if args.engine == "cycles":
        scene.render.engine = "CYCLES"
        enable_gpu()
        scene.cycles.device = "GPU"
        scene.cycles.samples = args.samples
    else:
        # EEVEE Next in Blender 4.2+, legacy name fallback for safety
        try:
            scene.render.engine = "BLENDER_EEVEE_NEXT"
        except TypeError:
            scene.render.engine = "BLENDER_EEVEE"
        if hasattr(scene, "eevee"):
            try:
                scene.eevee.taa_render_samples = args.samples
            except AttributeError:
                pass

    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "HIGH"
    scene.render.ffmpeg.audio_codec = "NONE"


# ---------------------------------------------------------------- props
def _make_box(name, center, dims, mat):
    """A box of full size `dims` centered at world `center` (primitive cube spans -1..1 -> scale=dim/2)."""
    bpy.ops.mesh.primitive_cube_add(location=tuple(center))
    o = bpy.context.active_object
    o.name = name
    o.scale = (dims[0] / 2.0, dims[1] / 2.0, dims[2] / 2.0)
    o.data.materials.append(mat)
    return o


def add_bench(center, size, rgb):
    """A simple seat (box) the characters sit on, so they're not floating."""
    return _make_box("bench", center, size, colored_mat("bench", tuple(rgb), rough=0.8))


# ---------------------------------------------------------------- motion + placement
def load_motion_onto(char_arm, motion_spec):
    """Apply an animation to char_arm without retargeting (works when the motion's skeleton matches
    the character's bone names). motion_spec is "<file>" or "<file>#<ActionName>"."""
    path, _, want = motion_spec.partition("#")
    before = set(bpy.data.objects)
    import_model(path)
    new = [o for o in bpy.data.objects if o not in before]

    act = None
    if want:
        cands = [a for a in bpy.data.actions if a.name.split("|")[-1] == want or a.name.endswith(want)]
        act = cands[0] if cands else None
        if not act:
            avail = sorted({a.name.split("|")[-1] for a in bpy.data.actions})
            print(f"   [motion] WARNING action '{want}' not found. Available: {avail[:40]}")
    else:
        src = find_armature(new)
        act = src.animation_data.action if (src and src.animation_data) else None

    if act:
        bind_action(char_arm, act)                     # assign + bind slot; action survives src deletion
        print(f"   [motion] applied '{act.name}' to {char_arm.name}")
    else:
        print(f"   [motion] WARNING no action applied from {os.path.basename(path)}")
    for o in new:                                       # drop the motion's armature/mesh, keep the action
        bpy.data.objects.remove(o, do_unlink=True)
    return act is not None


def preload_actions(lib_path):
    """Import a motion-library FBX ONCE and return {clip_last_segment: action}, then delete its
    objects (the action datablocks persist). Avoids per-character re-import that renames clips
    to '...Loop.001' and breaks name lookup."""
    before = set(bpy.data.objects)
    before_acts = set(bpy.data.actions)
    import_model(lib_path)
    new = [o for o in bpy.data.objects if o not in before]
    amap = {}
    for a in bpy.data.actions:
        if a not in before_acts:
            a.use_fake_user = True                 # keep it alive after we delete the library armature
            amap.setdefault(a.name.split("|")[-1], a)
    for o in new:
        bpy.data.objects.remove(o, do_unlink=True)
    print(f"   [motion] preloaded {len(amap)} clips from {os.path.basename(lib_path)}")
    return amap


def apply_motion(char_arm, motion_path=None, action_obj=None):
    """Bind a preloaded library action, or a motion file, onto char_arm (no-op if neither)."""
    if char_arm and action_obj:
        shift_action_to_frame1(action_obj)            # clips in a multi-take library start at high frames
        bind_action(char_arm, action_obj)             # assign + bind slot (Blender 4.4+ requirement)
        fr = action_obj.frame_range
        print(f"   [motion] applied '{action_obj.name}' to {char_arm.name} | fcurves={len(action_obj.fcurves)} "
              f"range=({fr[0]:.0f},{fr[1]:.0f}) slots={len(getattr(action_obj, 'slots', []))}")
    elif motion_path and char_arm and os.path.exists(motion_path.split("#", 1)[0]):
        load_motion_onto(char_arm, motion_path)


def _park_under_empty(roots, loc, face_deg, scale=1.0):
    """Parent `roots` under a fresh Empty placed at `loc`, rotated `face_deg` about Z, scaled `scale`."""
    empty = bpy.data.objects.new(f"place_{len(bpy.data.objects)}", None)
    bpy.context.collection.objects.link(empty)
    for r in roots:
        r.parent = empty
        r.matrix_parent_inverse = empty.matrix_world.inverted()
    empty.scale = (scale, scale, scale)
    empty.location = Vector(loc)
    empty.rotation_euler = (0.0, 0.0, math.radians(face_deg))
    return empty


def place_character(model_path, loc, face_deg, motion_path=None, action_obj=None, target_height=1.7):
    """Import a model (FBX/glb), apply an animation, normalize height, and park it at `loc`/`face_deg`.
    Used for un-baked characters; baked assets use place_prebuilt instead."""
    before = set(bpy.data.objects)
    import_model(model_path)
    new = [o for o in bpy.data.objects if o not in before]
    char_arm = find_armature(new)
    apply_motion(char_arm, motion_path, action_obj)

    meshes = [o for o in new if o.type == "MESH"]
    mins, maxs = world_bbox(meshes) if meshes else (Vector((0, 0, 0)), Vector((1, 1, target_height)))
    scale = target_height / max(maxs.z - mins.z, 1e-4)   # normalize: Mixamo FBX often imports ~100x

    roots = [o for o in new if o.parent is None]
    empty = _park_under_empty(roots, loc, face_deg, scale)
    return empty, new, meshes


def place_prebuilt(blend_path, loc, face_deg, motion_path=None, action_obj=None):
    """Append a BAKED character.blend (already normalized + clothed) and park it at `loc`/`face_deg`.
    No height-normalize / re-clothe — that work was done by build_character. Returns (empty, objs, meshes)
    or (None, [], []) if the append yielded no armature (caller falls back to FBX import)."""
    objs = append_character(blend_path)
    char_arm = find_armature(objs)
    if not char_arm:
        for o in objs:
            bpy.data.objects.remove(o, do_unlink=True)
        return None, [], []
    apply_motion(char_arm, motion_path, action_obj)
    meshes = [o for o in objs if o.type == "MESH"]
    roots = [o for o in objs if o.parent is None]
    empty = _park_under_empty(roots, loc, face_deg, scale=1.0)   # char's own root carries the baked scale
    return empty, objs, meshes


def loop_action(objects, frame_end):
    """Make each armature's action repeat across the whole shot (CYCLES fcurve modifier),
    so a short walk cycle fills N frames instead of freezing after its own range."""
    for o in objects:
        ad = getattr(o, "animation_data", None)
        if ad and ad.action:
            for fc in ad.action.fcurves:
                if not any(m.type == "CYCLES" for m in fc.modifiers):
                    fc.modifiers.new(type="CYCLES")


def keyframe_walk(empty, loc_from, loc_to, frame_start, frame_end):
    """Translate a character from one position to another over the shot (for walk_in)."""
    empty.location = Vector(loc_from)
    empty.keyframe_insert("location", frame=frame_start)
    empty.location = Vector(loc_to)
    empty.keyframe_insert("location", frame=frame_end)


def frame_camera(targets_bbox, aspect, shot, move, frame_start, frame_end):
    """Place + aim a camera to frame the union bbox of the 'on' characters for a shot type."""
    mins, maxs = targets_bbox
    center = (mins + maxs) * 0.5
    size = maxs - mins
    maxdim = max(size.x, size.y, size.z, 0.5)
    factor = {"medium": 2.0, "two_shot": 2.6, "wide": 3.2, "over_shoulder": 1.8, "hero": 2.4}.get(shot, 2.4)
    back = maxdim * factor + 1.5
    eye_h = center.z + size.z * 0.12

    cam_data = bpy.data.cameras.new("cam")
    cam_data.lens = 50
    cam = bpy.data.objects.new("cam", cam_data)
    bpy.context.collection.objects.link(cam)
    look_at = Vector((center.x, center.y, center.z + size.z * 0.05))

    def place(b):
        cam.location = (center.x + b * 0.45, center.y - b, eye_h)
        aim(cam, look_at)

    if move == "push_in":
        place(back * 1.12)
        cam.keyframe_insert("location", frame=frame_start)
        cam.rotation_euler = cam.rotation_euler
        place(back * 0.92)
        cam.keyframe_insert("location", frame=frame_end)
    else:
        place(back)
    bpy.context.scene.camera = cam
    return cam


def render_shot(spec):
    """Render one shot (multi-character, framed camera, N frames) to a silent mp4."""
    reset_scene()
    hdri = spec.get("hdri")
    if hdri and os.path.exists(hdri):
        set_world_hdri(hdri, float(spec.get("hdri_strength", 1.0)))
        floor_color = (0.20, 0.22, 0.18)     # soft grass/neutral ground under an outdoor HDRI
    else:
        if hdri:
            print(f"   [hdri] NOT FOUND: {hdri} — download it; using flat world for now")
        set_world_color()
        floor_color = (0.04, 0.04, 0.05)

    positions = spec["positions"]
    frames = int(spec["frames"])
    fstart, fend = 1, max(2, frames)

    # Preload the shared motion library ONCE (any cast entry using "<lib>#Clip").
    lib_actions, lib_path = {}, None
    for c in spec["cast"]:
        if "#" in (c.get("motion") or ""):
            lib_path = c["motion"].split("#", 1)[0]
            break
    if lib_path:
        lib_actions = preload_actions(lib_path)

    placed = {}          # who -> (empty, all_objs, meshes)
    all_meshes = []
    for c in spec["cast"]:
        at = positions[c["at"]]
        motion, action_obj = c.get("motion"), None
        if motion and "#" in motion:
            clip = motion.split("#", 1)[1]
            action_obj = lib_actions.get(clip)
            if not action_obj:
                print(f"   [motion] WARNING clip '{clip}' not in library {sorted(lib_actions)[:30]}")
            motion = None

        # Prefer a baked character.blend (already normalized + clothed); fall back to FBX import.
        blend = c.get("blend")
        prebuilt = bool(blend and os.path.exists(blend))
        empty = char_arm = None
        if prebuilt:
            empty, new, meshes = place_prebuilt(os.path.abspath(blend), at["loc"], at.get("face", 0),
                                                motion_path=motion, action_obj=action_obj)
            if empty is None:
                print(f"   [char] baked blend had no rig; falling back to FBX for {c['who']}")
                prebuilt = False
        if not prebuilt:
            empty, new, meshes = place_character(os.path.abspath(c["model"]), at["loc"], at.get("face", 0),
                                                 motion_path=motion, action_obj=action_obj)
        char_arm = find_armature(new)

        # a garment carries its own copy of the shared rig — give EVERY armature the same motion so the
        # clothes deform identically and track the body
        for a in [o for o in new if o.type == "ARMATURE" and o is not char_arm]:
            apply_motion(a, motion, action_obj)

        # walk_in: face the direction of travel so the body doesn't slide sideways/backward.
        if c.get("to") and c["to"] in positions:
            d = Vector(positions[c["to"]]["loc"]) - Vector(at["loc"])
            if d.length > 1e-4:
                empty.rotation_euler = (0.0, 0.0, math.radians(
                    angle_to_face(d.x, d.y) + float(spec.get("walk_face_offset", 0.0))))

        # Clothing/skin: baked assets already carry it; only paint un-baked ones here.
        if not prebuilt:
            skin = c.get("color") or (0.80, 0.62, 0.50)
            cl = c.get("clothes")
            if not (cl and char_arm and clothe_body(meshes, char_arm, cl.get("kind", "casual"), skin,
                                                     tuple(cl.get("shirt", (0.94, 0.94, 0.97))),
                                                     tuple(cl.get("lower", (0.16, 0.18, 0.38))),
                                                     float(cl.get("baggy", 0.0)))):
                recolor_meshes(meshes, skin)     # fallback: flat single color (no clothes / no armature)

        loop_action(new, fend)
        if c.get("to") and c["to"] in positions:
            keyframe_walk(empty, at["loc"], positions[c["to"]]["loc"], fstart, fend)
        placed[c["who"]] = (empty, new, meshes)
        all_meshes += meshes

    # a seat the characters sit on (scene-level prop)
    bench = spec.get("bench")
    if bench:
        bloc = (positions[bench["at"]]["loc"] if bench.get("at") in positions else bench.get("loc", [0, 0, 0]))
        bsize = bench.get("size", [1.6, 0.55, 0.45])
        add_bench((bloc[0], bloc[1], bsize[2] / 2.0), bsize, bench.get("color", [0.30, 0.20, 0.12]))

    # floor sized to everything
    fmins, fmaxs = world_bbox(all_meshes)
    add_floor((fmins + fmaxs) * 0.5, fmaxs - fmins, color=floor_color)

    # camera frames just the 'on' characters
    cam = spec.get("camera", {})
    on = cam.get("on") or list(placed.keys())
    on_meshes = [m for who in on if who in placed for m in placed[who][2]]
    add_three_point((fmins + fmaxs) * 0.5, fmaxs - fmins)
    frame_camera(world_bbox(on_meshes or all_meshes), spec["aspect"],
                 cam.get("shot", "wide"), cam.get("move", "static"), fstart, fend)

    # render config
    args = argparse.Namespace(aspect=spec["aspect"], fps=int(spec.get("fps", 30)),
                              engine=spec.get("engine", "eevee"), samples=int(spec.get("samples", 64)))
    configure_render(args)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = fstart, fend
    scene.frame_set(fstart)
    out = os.path.abspath(spec["out"])
    os.makedirs(os.path.dirname(out), exist_ok=True)
    scene.render.filepath = out
    print(f"[shot] {spec.get('id','?')} {spec['aspect']} cast={[c['who'] for c in spec['cast']]} "
          f"shot={cam.get('shot')} frames {fstart}-{fend} -> {out}", flush=True)
    bpy.ops.render.render(animation=True)
    print(f"[done] {out}", flush=True)


def main():
    args = parse_args()
    if args.shot:
        spec = json.loads(open(os.path.abspath(args.shot), encoding="utf-8").read())
        render_shot(spec)
        return
    if not args.model:
        raise SystemExit("need --shot <spec.json> (M1) or --model <file> (M0)")
    model_path = os.path.abspath(args.model)
    if not os.path.exists(model_path):
        raise SystemExit(f"[error] model not found: {model_path}")

    reset_scene()
    objs = import_model(model_path)
    mins, maxs = world_bbox(objs)
    center = (mins + maxs) * 0.5
    size = maxs - mins
    print(f"[scene] bbox size=({size.x:.2f},{size.y:.2f},{size.z:.2f}) center=({center.x:.2f},{center.y:.2f},{center.z:.2f})")

    set_world_color()
    add_floor(center, size)
    add_three_point(center, size)
    add_camera(center, size, args.aspect)

    configure_render(args)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = animation_range(objs, args.fps, args.seconds)

    out = os.path.abspath(f"{args.out}.{args.aspect}.mp4")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    scene.render.filepath = out
    print(f"[render] engine={scene.render.engine} {scene.render.resolution_x}x{scene.render.resolution_y} "
          f"frames {scene.frame_start}-{scene.frame_end} -> {out}")
    bpy.ops.render.render(animation=True)
    print(f"[done] {out}")


if __name__ == "__main__":
    main()
