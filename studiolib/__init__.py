"""studiolib — the shared math/tools layer for anim-studio (Blender-python side).

Components (renderer, character builder) compose these helpers instead of duplicating bpy/mathutils
logic. Import it from a script run under Blender's python after adding the anim-studio dir to sys.path:

    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from studiolib import import_model, detect_rig, clothe_body, validate_character, ...

Modules: geometry (bbox/scale/facing), rig (armature/bone-map/actions), meshpaint (recolor/clothing),
blendio (import/append/save), validate (checks).
"""
from .geometry import (angle_to_face, center_dims, feet_to_origin, height_scale, world_bbox)
from .rig import (BONE_ROLES, bind_action, bone_map, bone_z_world, detect_rig, find_armature,
                  find_bone, shift_action_to_frame1)
from .meshpaint import clothe_body, colored_mat, recolor_meshes
from .blendio import append_character, apply_all_transforms, import_model, save_blend
from .wardrobe import attach_garment
from .validate import format_report, tpose_check, validate_character

__all__ = [
    "angle_to_face", "center_dims", "feet_to_origin", "height_scale", "world_bbox",
    "BONE_ROLES", "bind_action", "bone_map", "bone_z_world", "detect_rig", "find_armature",
    "find_bone", "shift_action_to_frame1",
    "clothe_body", "colored_mat", "recolor_meshes",
    "append_character", "apply_all_transforms", "import_model", "save_blend",
    "attach_garment",
    "format_report", "tpose_check", "validate_character",
]
