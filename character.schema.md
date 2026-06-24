# Character recipe (`characters/<name>/character.yaml`)

The declarative input to **`build_character.py`** (Component 1). An AI or NK writes this; the tool bakes
a reusable, validated character asset next to it. The recipe is the **source of truth**; everything else
in the folder is generated.

```yaml
name: riya                                   # asset id (folder name); used by scenes via `use: riya`
source: "characters/.../Superhero_Female_FullBody.fbx"   # path under assets/ (rigged .fbx/.glb/.gltf)
target_height: 1.70                          # metres; the body is scaled to this
forward: +Y                                  # which local axis faces forward: +Y | -Y | +X | -X
rig: auto                                    # 'auto' = detect the bone map; or give an explicit bone_map
look:
  skin: [0.82, 0.60, 0.52]                   # skin RGB 0-1 (face / arms / legs)
  clothes: {kind: skirt, shirt: [0.96,0.80,0.25], lower: [0.80,0.22,0.38], baggy: 0.035}
voice: {engine: orpheus, voice: "ऋतिका", lang: hi}   # carried through so scenes can `use:` the character
```

## Fields
| key | meaning |
|---|---|
| `name` | asset id; the scene refers to it with `use: <name>` |
| `source` | rigged model path under `assets/` (or absolute) |
| `target_height` | metres to normalize the body to (default 1.70) |
| `forward` | local axis that should face the camera-forward (`+Y` default). Flip if the preview faces away |
| `rig` | `auto` to detect the canonical bone map, or an explicit `bone_map: {pelvis: ..., head: ...}` |
| `look.skin` | skin RGB where no clothing covers |
| `look.clothes` | *(painted)* `{kind: skirt\|shorts, shirt:[rgb], lower:[rgb], baggy:<m>}` — color regions painted onto the body mesh |
| `look.garment` | *(real clothing)* path under `assets/` to a garment mesh **skinned to the same rig** (e.g. Quaternius Modular Outfits). Bound to the body armature → deforms with animation. `skin` still applies to exposed body. |
| `look.textured` | `true` to keep the source model's own materials (clothed/textured model like Mixamo/VRoid) — no painting |
| `voice` | the character's voice spec (`engine: orpheus\|dots`, …), reused by scenes |

Pick exactly one clothing mode: `garment` (best, real mesh) **or** `clothes` (painted) **or** `textured`
(model already clothed). With `garment`/`clothes`, `skin` colors the exposed body.

## What the build produces (generated — don't hand-edit)
| file | what |
|---|---|
| `character.blend` | the baked character: normalized to `target_height`, feet at z=0, clothing painted. Scenes link this for fast loads. |
| `preview.png` | a front render to eyeball. |
| `character.resolved.yaml` | the recipe + **detected** `bone_map` and `measured_height` + a `built:` summary. |
| `character.resolved.json` | machine-readable resolved info + the validation report. |

## Generating a recipe from the catalog (the agent front door)
Rather than hand-writing the YAML, an agent picks building blocks from [`catalog.yaml`](catalog.yaml)
(bodies, outfits, skins, voices) and `new_character.py` writes the recipe:
```powershell
python new_character.py --list                                  # see options
python new_character.py --name riya --body female_base --outfit skirt_warm --voice ritika_hindi --build
```
Add more wardrobe later by adding entries under `outfits:` in the catalog — no code change.

## How an AI uses this
1. Write/edit `character.yaml` (pure declarative) — or generate it with `new_character.py` (above).
2. Run `python build_character.py characters/<name>/character.yaml`.
3. Read the printed **validation report** (rig present, bone_map complete, height≈target, feet on floor)
   and look at `preview.png`.
4. If something's off, edit the recipe and re-run — e.g. body faces away → flip `forward`; too tall/short
   → fix `target_height`; wrong colors → edit `look`. Deterministic, headless, no GUI needed.

## Using a built character in a scene
In a `*.scene.yaml`, a cast member can simply reference the asset:
```yaml
cast:
  riya: {use: riya}          # pulls model + skin + clothes + voice from characters/riya/character.yaml
  ram:  {use: ram, color: [0.7,0.55,0.45]}   # inline keys still override the recipe
```
The renderer links `characters/<name>/character.blend` when present (already normalized + clothed), and
falls back to importing the source model if the asset hasn't been baked yet.

See [`docs/CHARACTER_PIPELINE.md`](docs/CHARACTER_PIPELINE.md) for the pipeline internals and the GUI
inspection tutorial.
