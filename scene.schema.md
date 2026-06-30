# Scene schema (`*.scene.yaml`)

The 3D analogue of `skill45-video`'s `script.yaml`. An agent (or NK) authors this; `build_scene.py` turns
it into a stitched, voiced video. Designed to be **agent-generatable** and to **degrade gracefully** with
missing assets (a missing motion clip / HDRI falls back instead of failing). See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for how each key is consumed.

## Top level
| key | type | meaning |
|---|---|---|
| `title` | str | scene title |
| `fps` | int | frames/sec (default 30) |
| `aspects` | list | any of `16x9`, `9x16` (defaults to both if omitted; `--aspects` overrides) |
| `hdri` | str? | path under `assets/` to an `.hdr` — backdrop **and** image-based lighting. Missing → flat world |
| `hdri_strength` | float? | HDRI brightness (default 1.0) |
| `bench` | map? | a seat prop: `{loc: [x,y,z], size: [w,d,h], color: [r,g,b]}`. Top sits at height `h` |
| `walk_face_offset` | float? | degrees added to every walker's auto-facing (tune if a clip's forward ≠ +Y) |
| `motion_library` | str? | path under `assets/` to a multi-clip FBX (e.g. Quaternius `UAL1_Standard.fbx`) |
| `motion_map` | map? | semantic action name → clip name in the library (e.g. `walk_in: Jog_Fwd_Loop`) |
| `music` | str? | optional music-bed path (reuse skill45-video `uplift_bed.mp3`) |
| `positions` | map | named spots in the set → `{loc: [x,y,z], face: <deg>}` |
| `cast` | map | character id → `{model, color?, clothes?, voice}` (below) |
| `shots` | list | ordered shots (below) |

**`face` convention** — degrees about Z. Local **+Y is forward**; `face: 180` looks straight at the camera
(camera sits on −Y). `~200 / 160` give a 3/4 two-shot where both faces stay visible. Walkers (`to:`) get
their facing auto-set to the travel direction, so their `face` is ignored.

## cast entry
```yaml
riya:
  model: "characters/.../Superhero_Female_FullBody.fbx"   # rigged .glb/.gltf/.fbx under assets/
  color: [0.82, 0.60, 0.52]                               # skin tone (face/arms/legs)
  clothes: {kind: skirt,  shirt: [0.96, 0.80, 0.25], lower: [0.80, 0.22, 0.38], baggy: 0.035}
  voice: {engine: orpheus, voice: "ऋतिका", lang: hi}
ram:
  model: "characters/.../Superhero_Male_FullBody.fbx"
  color: [0.74, 0.56, 0.46]
  clothes: {kind: shorts, shirt: [0.20, 0.50, 0.88], lower: [0.92, 0.52, 0.12], baggy: 0.045}
  voice: {engine: dots, ref: nk_hi.wav, lang: hi}
```
- `model` — path under `assets/`, rigged. May be a **`.vrm`** (VRoid) — those keep their own
  textures (no recolor/clothing applied) and bring mouth visemes + emotion blendshapes for the face
  layer (M3). Needs the free *VRM Add-on for Blender* enabled.
- `color` — skin RGB (0–1); applied where no clothing covers. Without `clothes`, the whole body is this color.
- `clothes` — paints the body mesh into regions (no extra geometry, deforms with the pose):
  - `kind` — `skirt` (a touch longer) | `shorts`.
  - `shirt` / `lower` — RGB of the top and the skirt/shorts.
  - `baggy` — optional metres to puff the clothed band outward along normals (loose-fit look).
- `voice.engine` — `orpheus` (in-proc Hindi female ऋतिका) | `dots` (NK's cloned voice, genai subprocess).
- `voice.ref` — reference wav for dots cloning (relative to `dots-pilot/` or absolute).
- `voice.lang` — `hi` | `en`.

## shot entry
```yaml
- id: b2_ram_enters
  camera: {shot: wide, on: [riya, ram], move: push_in}   # shot: medium|wide|two_shot|over_shoulder|hero
  cast:
    - {who: riya, at: bench_seat, action: sit_scroll_phone}
    - {who: ram,  at: path, action: walk_in, to: bench_side}
  dialogue:
    - {who: ram, line: "अरे Riya! इतने ध्यान से क्या देख रही हो?"}
  seconds: 6        # optional; if omitted, computed from dialogue durations
```
- `camera.on` — which cast ids the camera frames; `shot` picks framing; `move` (optional) `push_in|static`.
- `cast[].at` — a named `position`; `cast[].to` — optional target position for a traveling action
  (the character walks from `at` to `to`, auto-facing the travel direction).
- `cast[].action` — a semantic name resolved in this priority:
  1. `motion_library` + `motion_map` → that library clip,
  2. else `assets/motions/<action>.fbx`,
  3. else the model's built-in clip / static pose (so incomplete scenes still render).
- `dialogue[].who` → that character's `voice`; `line` is Hinglish-in-Devanagari (Orpheus/dots read it).
- `dialogue[].emotion` — *optional* facial expression held over the line for VRM characters:
  `happy | sad | angry | surprised | relaxed | neutral` (default `neutral`). Ignored by body-only
  rigs. The mouth also lip-syncs to the line's audio amplitude automatically (M3 face layer).
- **Shot duration** = `seconds` if given, else `LEAD + Σ(line dur + GAP)`, floored at `MIN_SHOT` (2.5 s).

## Notes
- Lip-sync is NOT in the schema yet (M3) — mouths won't match words until then.
- One scene = one set; shots are hard-cut and concatenated (continuous camera is a later refinement).
- Bench seat-height (`bench.size[2]`, default 0.45 m) may need tuning to match a given sit clip's hips.
