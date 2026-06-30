"""mcp_studio — bpy-side toolkit for the live-MCP "story -> video" pipeline (anim-studio).

This module runs INSIDE Blender. An agent sends a tiny bootstrap through
`mcp__blender__execute_blender_code`:

    import sys
    sys.path.insert(0, r"C:\\Users\\ZENITHRA_MK\\Music\\NK\\Projects\\anim-studio\\agent")
    import mcp_studio, importlib; importlib.reload(mcp_studio)
    print(mcp_studio.build_story(r"<abs path to voice/<title>/manifest.json>"))

`build_story` composes the characters, faces them, adds props, drives amplitude
lip-sync from the per-line envelopes, sets fps, and renders a SILENT mp4. The host
script `assemble_story.py` then muxes the voices + appends the end card.

Every hard-won gotcha is encapsulated here so a fresh agent never rediscovers them:
  * reset with read_homefile(use_empty=True) — NEVER read_factory_settings (kills the MCP bridge).
  * HDRI set directly via shader nodes (the Poly Haven MCP toggle dies after a scene reset).
  * characters appended then PREFIX-RENAMED immediately (avoids name collisions on the 2nd load).
  * lip-sync keyframes a FIXED rest-Z (reading the animated z as the base compounds into a gap).
  * sc.render.fps is forced (Blender defaults to 24 -> audio/lips desync against 30fps offsets).

Input is pure JSON (json is stdlib) so Blender's bundled Python needs no extra packages.
"""
import json
import math
import os

import bpy
from mathutils import Vector


# ----------------------------------------------------------------------------- scene reset / world
def reset_scene():
    """Empty the scene WITHOUT killing the MCP bridge.

    GOTCHA: bpy.ops.wm.read_factory_settings() disables add-ons -> the BlenderMCP socket
    dies and the agent loses control. read_homefile(use_empty=True) gives a clean empty
    scene and keeps the bridge alive.
    """
    bpy.ops.wm.read_homefile(use_empty=True)
    return bpy.context.scene.collection


def set_hdri(path, strength=1.0):
    """World = an HDRI image (realistic backdrop + image-based lighting in one).

    GOTCHA: after a scene reset the Poly Haven MCP commands stop working (their toggle
    resets), so we build the world node graph directly: TexEnvironment -> Background -> Output.
    """
    path = os.path.abspath(path)
    world = bpy.data.worlds.new("studio")
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    bg = nt.nodes.new("ShaderNodeBackground")
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    out = nt.nodes.new("ShaderNodeOutputWorld")
    if not os.path.exists(path):
        print(f"[mcp_studio] HDRI not found: {path} — flat sky")
        bg.inputs["Color"].default_value = (0.05, 0.06, 0.09, 1.0)
    else:
        env.image = bpy.data.images.load(path)
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = float(strength)
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    print(f"[mcp_studio] world = {os.path.basename(path)} (strength {strength})")


def add_lights_and_camera(coll, cam_loc=(0.0, -7.0, 1.45), lens=45.0):
    """Deterministic key+fill area lights and a front render camera (matches the
    two-shot framing used for the Ram & Riya story). HDRI adds the soft ambient."""
    def area(name, loc, energy, size):
        d = bpy.data.lights.new(name, "AREA")
        d.energy, d.size = energy, size
        o = bpy.data.objects.new(name, d)
        coll.objects.link(o)
        o.location = loc
        # point roughly at the characters' chest height at origin
        o.rotation_euler = _look_at(Vector(loc), Vector((0, 0, 1.4)))
        return o
    area("key", (2.2, -2.6, 3.6), 700.0, 5.0)
    area("fill", (-2.5, -1.5, 2.0), 250.0, 6.0)
    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = lens
    cam = bpy.data.objects.new("Camera", cam_data)
    coll.objects.link(cam)
    cam.location = cam_loc
    cam.rotation_euler = (math.radians(90.0), 0.0, 0.0)  # horizontal, looking +Y
    bpy.context.scene.camera = cam
    return cam


def _look_at(eye, target):
    d = (target - eye)
    return d.to_track_quat("-Z", "Y").to_euler()


# ----------------------------------------------------------------------------- character compose
def place_character(blend, prefix, x, face_deg):
    """Append a character from its .blend, park it under a new Empty, prefix-rename, place & face.

    GOTCHA: rename objects to `prefix+name` IMMEDIATELY after each load — otherwise the second
    character's identically-named objects (head, upper_lip, ...) collide and Blender mangles them.
    Only MESH/ARMATURE/EMPTY are placed; a source blend's own Camera/Light are skipped.
    """
    blend = os.path.abspath(blend)
    coll = bpy.context.scene.collection
    with bpy.data.libraries.load(blend, link=False) as (src, dst):
        dst.objects = list(src.objects)
    added = [o for o in dst.objects if o and o.type in {"MESH", "ARMATURE", "EMPTY"}]
    for o in added:
        coll.objects.link(o)
    empty = bpy.data.objects.new(prefix + "root", None)
    coll.objects.link(empty)
    for o in added:
        if o.parent is None:
            o.parent = empty
            o.matrix_parent_inverse = empty.matrix_world.inverted()
    for o in added:                       # rename AFTER linking/parenting, BEFORE the next load
        o.name = prefix + o.name
    empty.location = (x, 0.0, 0.0)
    empty.rotation_euler = (0.0, 0.0, math.radians(face_deg))
    print(f"[mcp_studio] placed {prefix} from {os.path.basename(blend)} at x={x} face={face_deg}")
    return empty


def add_phone(loc, rot_deg):
    """Skill45-blue glowing phone (dark body + emissive screen) — the 'showing the app' prop."""
    coll = bpy.context.scene.collection
    bpy.ops.mesh.primitive_cube_add(size=1)
    body = bpy.context.view_layer.objects.active
    body.name = "phone_body"
    body.scale = (0.16, 0.012, 0.30)
    b = body.modifiers.new("bev", "BEVEL"); b.width = 0.012; b.segments = 3
    mat = bpy.data.materials.new("phone_mat"); mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.04, 0.04, 0.05, 1)
    bsdf.inputs["Roughness"].default_value = 0.3
    body.data.materials.append(mat)
    bpy.ops.mesh.primitive_plane_add(size=1)
    scr = bpy.context.view_layer.objects.active
    scr.name = "phone_screen"
    scr.rotation_euler[0] = math.radians(90)
    scr.scale = (0.14, 0.27, 1)
    scr.location = (0, -0.014, 0)
    smat = bpy.data.materials.new("screen_mat"); smat.use_nodes = True
    sb = smat.node_tree.nodes["Principled BSDF"]
    sb.inputs["Base Color"].default_value = (0.10, 0.45, 0.95, 1)
    sb.inputs["Emission Color"].default_value = (0.15, 0.55, 1.0, 1)
    sb.inputs["Emission Strength"].default_value = 2.5
    scr.data.materials.append(smat)
    root = bpy.data.objects.new("phone_root", None); coll.objects.link(root)
    for o in (body, scr):
        o.parent = root
        o.matrix_parent_inverse = root.matrix_world.inverted()
    root.location = tuple(loc)
    root.rotation_euler = tuple(math.radians(d) for d in rot_deg)
    print(f"[mcp_studio] phone at {loc}")
    return root


# ----------------------------------------------------------------------------- lip-sync + blink
def _obj(prefix, name):
    return bpy.data.objects.get(prefix + name)


def lipsync(prefix, meta, env, frame_start, fps):
    """Keyframe the lips' object location.z from the amplitude envelope.

    GOTCHA: the rest (closed) Z comes from `meta` (a FIXED constant), never from reading the
    object's current/animated z — re-keying off an animated value compounds into a permanent gap.
    Upper lip moves up by open_up*o, lower lip down by open_down*o, where o = min(1, amp*gain).
    """
    up = _obj(prefix, meta["upper_lip"])
    lo = _obj(prefix, meta["lower_lip"])
    if not (up and lo):
        print(f"[mcp_studio] {prefix}: lips not found — skipping lip-sync")
        return
    ru, rl = float(meta["rest_upper_z"]), float(meta["rest_lower_z"])
    ou, od, gain = float(meta["open_up"]), float(meta["open_down"]), float(meta.get("gain", 1.5))
    n = len(env)

    def key(f, uz, lz):
        up.location.z = uz; up.keyframe_insert("location", index=2, frame=f)
        lo.location.z = lz; lo.keyframe_insert("location", index=2, frame=f)

    key(max(1, frame_start - 1), ru, rl)            # closed just before the line
    for i in range(n):
        o = min(1.0, env[i] * gain)
        key(frame_start + i, ru + ou * o, rl - od * o)
    key(frame_start + n, ru, rl)                    # close again after the line
    print(f"[mcp_studio] {prefix}: lip-sync {n} frames @ {frame_start}")


def idle_blink(prefix, meta, frame_end, fps, period_s=3.2, dur_f=3):
    """Periodic blink: squash the listed eye objects on Z for a few frames."""
    eyes = [_obj(prefix, n) for n in meta.get("eyes", [])]
    eyes = [e for e in eyes if e]
    if not eyes:
        return
    rest = {e.name: e.scale.z for e in eyes}
    step = max(1, int(period_s * fps))
    for e in eyes:                                  # baseline open at frame 1
        e.scale.z = rest[e.name]; e.keyframe_insert("scale", index=2, frame=1)
    f = step
    while f < frame_end - dur_f:
        for e in eyes:
            e.keyframe_insert("scale", index=2, frame=f - 1)
            e.scale.z = rest[e.name] * 0.1; e.keyframe_insert("scale", index=2, frame=f + dur_f // 2)
            e.scale.z = rest[e.name]; e.keyframe_insert("scale", index=2, frame=f + dur_f)
        f += step


# ----------------------------------------------------------------------------- render
def render_silent(out_path, frame_end, fps=30, res=(1280, 720), samples=32):
    """Render frames 1..frame_end to a SILENT mp4 (audio is muxed later by ffmpeg).

    GOTCHA: force sc.render.fps — Blender defaults to 24, and the dialogue offsets were
    computed at `fps`; a 24fps render desyncs voice + lips.
    """
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, int(frame_end)
    sc.render.fps = int(fps)                          # <- the desync fix
    sc.render.resolution_x, sc.render.resolution_y = res
    try:
        sc.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        sc.render.engine = "BLENDER_EEVEE"
    if hasattr(sc, "eevee"):
        try:
            sc.eevee.taa_render_samples = samples
        except AttributeError:
            pass
    sc.render.image_settings.file_format = "FFMPEG"
    sc.render.ffmpeg.format = "MPEG4"
    sc.render.ffmpeg.codec = "H264"
    sc.render.ffmpeg.constant_rate_factor = "HIGH"
    sc.render.ffmpeg.audio_codec = "NONE"
    sc.render.filepath = out_path
    bpy.ops.render.render(animation=True)
    ok = os.path.exists(out_path)
    print(f"[mcp_studio] rendered {'OK' if ok else 'FAILED'} -> {out_path}")
    return ok


# ----------------------------------------------------------------------------- driver
def build_story(manifest_path):
    """Top-level driver. Reads the self-contained manifest.json (written by assemble_story.py
    `voices`), composes the whole scene, drives lip-sync, and renders the silent mp4.

    Returns a JSON string the agent can parse: {ok, out_silent, frame_end, characters, lines}.
    """
    with open(manifest_path, "r", encoding="utf-8") as fh:
        m = json.load(fh)
    fps = int(m.get("fps", 30))
    frame_end = int(m["frame_end"])

    coll = reset_scene()
    bg = m.get("background") or {}
    if bg.get("hdri"):
        set_hdri(bg["hdri"], bg.get("strength", 1.0))
    add_lights_and_camera(coll)

    # place every character + cache its face meta
    metas = {}
    for who, c in m["characters"].items():
        place_character(c["blend"], c["prefix"], c["x"], c["face"])
        with open(c["face_json"], "r", encoding="utf-8") as fh:
            metas[who] = json.load(fh)

    for p in m.get("props", []) or []:
        if p.get("kind") == "phone":
            add_phone(p["loc"], p["rot"])

    # set the render range BEFORE keyframing so the closing keys land inside the timeline
    bpy.context.scene.frame_end = frame_end

    spoke = set()
    for ln in m["lines"]:
        who = ln["who"]
        meta = metas.get(who)
        if not meta:
            continue
        lipsync(m["characters"][who]["prefix"], meta, ln["env"], int(ln["frame_start"]), fps)
        spoke.add(who)

    for who in spoke:                                   # blink only the speakers, for life
        idle_blink(m["characters"][who]["prefix"], metas[who], frame_end, fps)

    ok = render_silent(m["out_silent"], frame_end, fps=fps)
    return json.dumps({"ok": ok, "out_silent": os.path.abspath(m["out_silent"]),
                       "frame_end": frame_end, "characters": list(m["characters"]),
                       "lines": len(m["lines"])})
