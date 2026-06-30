# Agent Playbook — Story → Video (live-MCP path)

**Purpose.** Hand any agent (a local model, another cloud model, me) a *story script* and it produces
a voiced, lip-synced, multi-character animated video — by following this one document. No re-deriving
the recipe each time. The pattern was lifted verbatim from the Ram & Riya garden video.

**What it produces.** Our own primitive `.blend` characters, placed in a scene facing each other,
each lip-syncing to its spoken line (NK's cloned voice and/or a Hindi female voice), over an HDRI
backdrop, with an optional prop and a Skill45 end card → `out/<title>.mp4`.

**What an agent needs (the contract):**
1. the **Blender MCP** tools (`mcp__blender__execute_blender_code`, `…get_scene_info`,
   `…get_viewport_screenshot`) with Blender open and connected, AND
2. **shell access** to run two host scripts with the `skill45video` Python.

That's the whole plug surface. If an agent has both, it can run the pattern.

---

## The pattern: 4 stages

| Stage | Tool | Command / call |
|-------|------|----------------|
| 0 · Capability check | shell + 3 MCP probes | `check_tools.py` + the probes below |
| 1 · Write story | author | edit a `stories/<name>.story.yaml` (see `story.schema.md`) |
| 2 · Voices | shell | `assemble_story.py voices stories/<name>.story.yaml` |
| 3 · Compose + render | Blender MCP | `mcp_studio.build_story(<manifest.json>)` (bootstrap below) |
| 4 · Assemble | shell | `assemble_story.py mux stories/<name>.story.yaml` |

Run them in order. Stage 2 writes a self-contained `voice/<title>/manifest.json`; stage 3 reads it
and renders the silent video; stage 4 muxes the voices + appends the end card.

The `skill45video` Python (used for stages 0, 2, 4):
```
C:\Users\ZENITHRA_MK\.conda\envs\skill45video\python.exe
```
All shell commands run from the project root: `C:\Users\ZENITHRA_MK\Music\NK\Projects\anim-studio`.

---

## Stage 0 — capability check

**Shell half** (envs / ffmpeg / Blender / assets):
```powershell
$env:PYTHONUTF8 = "1"
& "$env:USERPROFILE\.conda\envs\skill45video\python.exe" agent/check_tools.py --story stories/ram_riya.story.yaml
```
Expect every line `[PASS]` and a final `== ALL PASS ==`. It exits non-zero on any failure — gate on it.

**MCP half** (only the agent can test its own tool access — run these 3 probes):

1. Scene reachable:
   ```
   mcp__blender__get_scene_info
   ```
   → returns a JSON scene description (not an error).
2. Code execution:
   ```python
   # mcp__blender__execute_blender_code
   import bpy; print("BLENDER", bpy.app.version_string)
   ```
   → prints `BLENDER 4.5.x`.
3. Viewport capture:
   ```
   mcp__blender__get_viewport_screenshot
   ```
   → returns an image.

If all three succeed **and** the shell check is ALL PASS, the agent can run the pipeline.

---

## Stage 1 — write the story

Copy `stories/ram_riya.story.yaml` and edit it. Full field reference: **`story.schema.md`**. Minimum:
a `title`, `background.hdri`, two `characters` (each a `.blend` + `x` + `face` + `voice`), and a
`dialogue` list. Keep `fps: 30`.

---

## Stage 2 — voices (shell)
```powershell
$env:PYTHONUTF8 = "1"
& "$env:USERPROFILE\.conda\envs\skill45video\python.exe" agent/assemble_story.py voices stories/ram_riya.story.yaml
```
Writes `voice/<title>/manifest.json` (per-line wav, dur, amplitude envelope, offset, frame range +
the resolved scene). Sanity: each line prints `frames=<N>` and `dur`; `frame_end` ≈ total seconds×30.

---

## Stage 3 — compose + render (Blender MCP)

Send **exactly this** through `mcp__blender__execute_blender_code` (fix the two absolute paths):
```python
import sys, importlib
sys.path.insert(0, r"C:\Users\ZENITHRA_MK\Music\NK\Projects\anim-studio\agent")
import mcp_studio; importlib.reload(mcp_studio)
print(mcp_studio.build_story(
    r"C:\Users\ZENITHRA_MK\Music\NK\Projects\anim-studio\voice\ram_riya\manifest.json"))
```
It prints a JSON summary like `{"ok": true, "out_silent": "...out/ram_riya.silent.mp4", ...}`.
Then **verify visually**:
```
mcp__blender__get_viewport_screenshot
```
→ both characters facing each other, the phone between them. If a face is turned the wrong way, flip
the sign of that character's `face` in the story and re-run stages 2–3 (or just nudge in Blender).

---

## Stage 4 — assemble (shell)
```powershell
& "$env:USERPROFILE\.conda\envs\skill45video\python.exe" agent/assemble_story.py mux stories/ram_riya.story.yaml
```
Muxes each voice line at its offset, appends the end card with a 0.5s fade → `out/<title>.mp4`, and
prints the final duration. Done.

---

## Gotchas (already baked into the code — here so you know *why*)

| Gotcha | Where it's handled | Why it matters |
|--------|-------------------|----------------|
| `read_factory_settings()` disables add-ons → **kills the MCP bridge** | `mcp_studio.reset_scene` uses `read_homefile(use_empty=True)` | the agent would lose control of Blender mid-run |
| Blender defaults to **24 fps** | `mcp_studio.render_silent` forces `sc.render.fps=30` | offsets/lips computed at 30 → 24fps desyncs voice |
| 2nd character's objects **collide** (head, upper_lip…) | `place_character` prefix-renames right after load | meshes get mangled / lip-sync drives the wrong object |
| Re-keying lips off the **animated** z compounds into a permanent gap | `lipsync` uses FIXED `rest_*_z` from `face.json` | mouth never closes; grows a gap over time |
| Poly Haven MCP commands **die after a scene reset** | `set_hdri` builds the world node graph directly | background silently fails to load |
| Devanagari crashes a redirected **Windows console** (cp1252) | `assemble_story` sets UTF-8 + `encoding="utf-8"` everywhere | stage 2 crashes on Hindi lines |

---

## Plug a new character
1. Build/keep the character as a `.blend` with lips as separate **`upper_lip`/`lower_lip`** objects.
2. Add a sidecar **`<stem>.face.json`** beside it (copy `characters/cute_char.face.json`): the
   unprefixed object names, the closed-mouth `rest_upper_z`/`rest_lower_z` (read them at the
   closed frame), the `open_up`/`open_down` deltas, `gain`, and the `eyes` list for blinks.
3. Reference `blend:` + `x`/`face`/`voice` in a story. No code change — `place_character` +
   `lipsync` are generic over `face.json`.

## Plug a new agent
Give the new agent this folder and tell it to run **Stage 0**. If the shell check is ALL PASS and the
3 MCP probes succeed, it can run stages 1–4 with no further setup. If a probe fails, it lacks that
capability (no Blender MCP, or no shell) and can't drive this pipeline — fix that before proceeding.

---

## Files
```
agent/AGENT_PLAYBOOK.md     # this file — the pattern
agent/story.schema.md       # the *.story.yaml input format
agent/check_tools.py        # Stage 0 host capability self-test
agent/assemble_story.py     # Stage 2 (voices) + Stage 4 (mux + end card)
agent/mcp_studio.py         # Stage 3 bpy-side toolkit (run inside Blender via the MCP)
stories/ram_riya.story.yaml # worked example (reproduces the Ram & Riya video)
characters/<stem>.face.json # per-character face metadata (lips, rest-Z, eyes)
```

## Honest limits
- Lip-sync is **amplitude-based** (mouth flap, not phoneme-accurate). Swap `lipsync()` for a viseme
  driver (Rhubarb / Audio2Face) later behind the same interface.
- Characters must be **our primitive `.blend`s** with `upper_lip`/`lower_lip` objects + a `face.json`.
  VRM / shape-key characters use the separate `studiolib/face.py` path, not this one.
- One set, fixed two-shot camera (no cuts). Camera grammar is future work.
