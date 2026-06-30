"""Import / append / save helpers for model files and .blend assets."""
import os

import bpy


def _ensure_vrm_addon():
    """Enable the VRM add-on for THIS (headless) session so we don't depend on saved GUI prefs.

    Works when the add-on is INSTALLED (present in Blender's add-ons path) even if it was never
    enabled / preferences weren't saved. If it isn't installed at all, this is a no-op and the
    import call below raises the actionable message.
    """
    import addon_utils
    mods = [m.__name__ for m in addon_utils.modules() if "vrm" in m.__name__.lower()]
    for mod in mods + ["io_scene_vrm"]:
        try:
            addon_utils.enable(mod, default_set=True, persistent=True)
            print(f"[vrm] enabled add-on: {mod}")
            return
        except Exception:                                    # noqa: BLE001 — try the next candidate
            continue


def import_model(path):
    """Import a .glb/.gltf/.fbx/.obj/.vrm; return the list of newly-created objects.
    .vrm (anime characters from VRoid Studio) needs the free 'VRM Add-on for Blender'."""
    if not os.path.exists(path):
        raise SystemExit(f"[error] model file not found: {path}\n"
                         "  (the importer silently produces 0 objects for a missing file)")
    before = set(bpy.data.objects)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".vrm":
        # Force-enable the add-on for this headless session (no reliance on saved GUI prefs).
        _ensure_vrm_addon()
        # bpy.ops attrs are lazy (hasattr always True), so detect the addon by trying the call and
        # turning the "operator not found" error into a clear, actionable message.
        try:
            bpy.ops.import_scene.vrm(filepath=path)
        except (AttributeError, RuntimeError) as e:
            raise SystemExit(
                "[error] .vrm import failed — the free 'VRM Add-on for Blender' is not enabled.\n"
                "  1. Download it: https://vrm-addon-for-blender.info/en/\n"
                "  2. Blender 4.5 > Edit > Preferences > Add-ons > Install... > pick the .zip\n"
                "  3. TICK the checkbox to ENABLE it, then re-run.\n"
                f"  (underlying error: {type(e).__name__}: {e})") from e
    else:
        raise SystemExit(f"[error] unsupported model type: {ext}")
    new = [o for o in bpy.data.objects if o not in before]
    print(f"[import] {os.path.basename(path)} -> {len(new)} objects")
    return new


def apply_all_transforms(objects):
    """Apply loc/rot/scale on mesh + armature objects (bake the transform into the data).
    Optional cleanup; uses temp_override so it works headless. Not used by the default build
    (we keep an empty's scale instead, which is safer with skinned meshes)."""
    for o in [o for o in objects if o.type in ("MESH", "ARMATURE")]:
        try:
            with bpy.context.temp_override(active_object=o, selected_objects=[o],
                                           selected_editable_objects=[o]):
                bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        except Exception as e:
            print(f"   [io] transform_apply failed on {o.name}: {e}")


def save_blend(path):
    """Save the current file as `path` (the build script starts from an empty scene, so the file
    contains only the character)."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=path)
    print(f"[io] saved {path}")


def append_character(blend_path, names=None):
    """Append objects from a baked character .blend into the current scene and link them to the
    active collection. Appends all objects by default (the asset file holds only the character).
    Returns the newly-linked objects."""
    blend_path = os.path.abspath(blend_path)
    with bpy.data.libraries.load(blend_path, link=False) as (src, dst):
        dst.objects = list(src.objects) if names is None else [n for n in src.objects if n in names]
    new = [o for o in dst.objects if o is not None]
    for o in new:
        bpy.context.collection.objects.link(o)
    print(f"[io] appended {len(new)} object(s) from {os.path.basename(blend_path)}")
    return new
