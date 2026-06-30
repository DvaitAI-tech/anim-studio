"""Facial animation for VRM characters — lip-sync + expression. Runs INSIDE Blender (bpy only).

VRoid `.vrm` characters import with shape keys (blendshapes) on the face mesh:
  - mouth visemes:  VRM 0.x = `A I U E O`        ·  VRM 1.0 = `aa ih ou ee oh`
  - expressions:    VRM 0.x = `Joy Angry Sorrow Fun Blink`  ·  VRM 1.0 = `happy angry sad relaxed surprised blink`

This module drives those shape keys from a per-line amplitude envelope (crude amplitude→open-mouth
lip-sync) and an emotion tag (an expression hold over the line). It is intentionally tolerant:
body-only rigs (Quaternius) have NO shape keys, so every function no-ops with a printed warning and
the scene renders unchanged. Phoneme-accurate visemes (Rhubarb / Audio2Face) are a later upgrade
behind this same interface — only `resolve_morphs` + `keyframe_mouth` would change.

Shape-key animation lives on `mesh.data.shape_keys.animation_data`, independent of the armature
action, so this never conflicts with body motion / loop_action.
"""

# Logical viseme/expression -> candidate shape-key names (lowercased), covering VRM 0.x and 1.0.
_MOUTH_OPEN = ["a", "aa"]              # the wide-open viseme we modulate for amplitude lip-sync
_EXPRESSION = {
    "happy":     ["happy", "joy"],
    "sad":       ["sad", "sorrow"],
    "angry":     ["angry"],
    "surprised": ["surprised", "surprise"],
    "relaxed":   ["relaxed", "fun"],
    "neutral":   ["neutral"],
}
_BLINK = ["blink"]


def find_face_meshes(objs):
    """Meshes carrying multiple shape keys (the VRM face mesh; body-only rigs return none)."""
    out = []
    for o in objs:
        if o.type == "MESH" and o.data.shape_keys and len(o.data.shape_keys.key_blocks) > 1:
            out.append(o)
    return out


def _find(mesh, names):
    """Find a key_block whose (lowercased) name equals, then loosely contains, any candidate."""
    lut = {kb.name.lower(): kb for kb in mesh.data.shape_keys.key_blocks}
    for n in names:
        if n in lut:
            return lut[n]
    for key, kb in lut.items():
        if any(n in key for n in names):
            return kb
    return None


def resolve_morphs(mesh):
    """Map logical controls to this mesh's shape keys. {'mouth', 'expr': {emo: kb}, 'blink', 'found'}."""
    mouth = _find(mesh, _MOUTH_OPEN)
    expr = {}
    for emo, names in _EXPRESSION.items():
        kb = _find(mesh, names)
        if kb:
            expr[emo] = kb
    blink = _find(mesh, _BLINK)
    found = ([mouth.name] if mouth else []) + [kb.name for kb in expr.values()] \
        + ([blink.name] if blink else [])
    return {"mouth": mouth, "expr": expr, "blink": blink, "found": found}


def _key(kb, value, frame):
    kb.value = max(0.0, min(1.0, value))
    kb.keyframe_insert("value", frame=int(frame))


def keyframe_mouth(mesh, morphs, envelope, frame_start, fps, gain=1.6):
    """Modulate the open-mouth viseme by the audio amplitude envelope (one value per frame).
    Closes the mouth one frame before the line and at its end. Returns the keyframes inserted."""
    kb = morphs.get("mouth")
    if not kb:
        print("   [face] no open-mouth viseme found — skipping lip-sync")
        return 0
    n = 0
    _key(kb, 0.0, max(1, frame_start - 1)); n += 1
    for i, amp in enumerate(envelope):
        _key(kb, amp * gain, frame_start + i); n += 1
    _key(kb, 0.0, frame_start + len(envelope)); n += 1
    return n


def keyframe_expression(mesh, morphs, emotion, frame_start, frame_end, peak=0.8, fade=6):
    """Hold an emotion blendshape across the line, ramping in/out over `fade` frames."""
    if not emotion or emotion == "neutral":
        return
    kb = morphs.get("expr", {}).get(emotion)
    if not kb:
        print(f"   [face] no expression blendshape for '{emotion}' — skipping")
        return
    _key(kb, 0.0, max(1, frame_start - fade))
    _key(kb, peak, frame_start)
    _key(kb, peak, frame_end)
    _key(kb, 0.0, frame_end + fade)


def idle_blink(mesh, morphs, frame_start, frame_end, fps, every=3.0):
    """Periodic 2-frame blink so the character isn't glassy-eyed. No-op without a blink shape."""
    kb = morphs.get("blink")
    if not kb:
        return
    step = max(1, int(every * fps))
    f = frame_start + step
    while f < frame_end - 2:
        _key(kb, 0.0, f - 2)
        _key(kb, 1.0, f)
        _key(kb, 0.0, f + 2)
        f += step
