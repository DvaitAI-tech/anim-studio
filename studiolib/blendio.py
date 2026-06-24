"""Import / append / save helpers for model files and .blend assets."""
import os

import bpy


def import_model(path):
    """Import a .glb/.gltf/.fbx/.obj/.vrm; return the list of newly-created objects.
    .vrm (anime characters from VRoid Studio) needs the free 'VRM Add-on for Blender'."""
    before = set(bpy.data.objects)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    elif ext == ".vrm":
        if not hasattr(bpy.ops.import_scene, "vrm"):
            raise SystemExit("[error] .vrm needs the free 'VRM Add-on for Blender' "
                             "(install it, then enable in Edit > Preferences > Add-ons). "
                             "See docs/CHARACTER_PIPELINE.md.")
        bpy.ops.import_scene.vrm(filepath=path)
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
