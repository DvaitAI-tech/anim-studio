"""Material painting: a flat recolor, and region-painted 'clothing' on the body mesh itself.

We don't add garment geometry (floating boxes clip badly). Instead we paint the real skinned body
mesh into skin / shirt / lower material regions by rest-pose height — so the clothing fits exactly
and deforms with every pose. `baggy` puffs the clothed band outward along normals for a loose look.
"""
import bpy

from .rig import bone_z_world, find_bone


def colored_mat(name, rgb, rough=0.75):
    """A flat Principled-BSDF material in `rgb` (0-1)."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    b = mat.node_tree.nodes.get("Principled BSDF")
    if b:
        b.inputs["Base Color"].default_value = (*rgb, 1)
        b.inputs["Roughness"].default_value = rough
    return mat


def recolor_meshes(meshes, rgb):
    """Override each mesh's materials with one flat color (base bodies import as magenta
    'missing texture'). Fallback when there's no rig / no clothing spec."""
    mat = colored_mat("charcolor", tuple(rgb), rough=0.6)
    for m in meshes:
        m.data.materials.clear()
        m.data.materials.append(mat)


def clothe_body(meshes, arm, kind, skin_rgb, shirt_rgb, lower_rgb, baggy=0.0):
    """Paint the BODY MESH ITSELF into skin / shirt / lower regions by rest-pose Z. Because it's the
    real skinned mesh, the 'clothing' fits the body exactly and deforms with every pose — no floating
    boxes, no legs poking through. Best-effort: returns False (never raises) on any problem.

    `baggy` (world metres) puffs the clothed-region verts outward along their normals (loose fit)."""
    try:
        pelvis = find_bone(arm, "pelvis", "hips", "hip")
        if not pelvis:
            print("   [cloth] no pelvis bone; skipping")
            return False
        neck = find_bone(arm, "neck")
        head = find_bone(arm, "head")
        knee = find_bone(arm, "calf_l", "shin_l", "lowerleg_l", "knee_l", "leftleg")
        thigh = find_bone(arm, "thigh_l", "upperleg_l", "leftupleg")

        hipz = bone_z_world(arm, pelvis)
        neckz = bone_z_world(arm, neck) or bone_z_world(arm, head) or (hipz + 0.55)
        thighz = bone_z_world(arm, thigh) or hipz
        kneez = bone_z_world(arm, knee) or (hipz - 0.45)

        shirt_top = neckz                                    # shirt covers torso up to the neck
        lower_top = hipz + (neckz - hipz) * 0.06             # waistband just above the hips
        skirt = (kind == "skirt")
        lower_bot = thighz - (thighz - kneez) * (0.80 if skirt else 0.55)   # skirt a touch longer

        skin_mat = colored_mat("skin", tuple(skin_rgb), rough=0.55)
        shirt_mat = colored_mat("shirt", tuple(shirt_rgb))
        lower_mat = colored_mat("lower", tuple(lower_rgb))
        for m in meshes:
            me = m.data
            me.materials.clear()
            me.materials.append(skin_mat)    # index 0
            me.materials.append(shirt_mat)   # index 1
            me.materials.append(lower_mat)   # index 2
            mw = m.matrix_world
            for poly in me.polygons:
                zc = sum((mw @ me.vertices[v].co).z for v in poly.vertices) / len(poly.vertices)
                if zc >= shirt_top:
                    poly.material_index = 0          # head / neck -> skin
                elif zc >= lower_top:
                    poly.material_index = 1          # torso + arms -> shirt
                elif zc >= lower_bot:
                    poly.material_index = 2          # hips + upper legs -> skirt/shorts
                else:
                    poly.material_index = 0          # lower legs -> skin

            if baggy > 0:                            # puff the clothed band outward = loose fit
                scale = max(m.matrix_world.to_scale().x, 1e-5)
                off = baggy / scale                  # mesh may be scaled by an empty; convert to local
                for v in me.vertices:
                    if lower_bot <= (mw @ v.co).z < shirt_top:
                        v.co = v.co + v.normal * off
        print(f"   [cloth] painted shirt+{kind} on body (hip={hipz:.2f} neck={neckz:.2f} knee={kneez:.2f})"
              f"{' +baggy' if baggy > 0 else ''}")
        return True
    except Exception as e:
        print(f"   [cloth] skipped ({e})")
        return False
