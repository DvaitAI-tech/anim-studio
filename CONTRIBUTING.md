# Contributing to anim-studio

Thanks for your interest! This project automates 3D character video with Blender + Python. It's early
and pragmatic — small, well-scoped contributions are the easiest to land.

## Ground rules
- Be kind and constructive. Assume good intent.
- By contributing, you agree your contributions are licensed under the repo's [MIT License](LICENSE).
- Don't commit large/binary assets (`.blend`, `.fbx`, `.vrm`, `.hdr`, `.wav`, `.mp4`, model weights) —
  they're `.gitignore`d on purpose. Keep PRs to code + docs + small recipe files (`*.yaml`,
  `*.face.json`).

## Setup
1. **Blender 4.5+** and the two Python envs described in the [README](README.md#prerequisites)
   (`skill45video` + `genai`). Tool paths are overridable via the `SKILL45_*` env vars.
2. Download the third-party assets you need (see [Acknowledgements](README.md#acknowledgements) and
   [`docs/CHARACTER_PIPELINE.md`](docs/CHARACTER_PIPELINE.md)). None are bundled.
3. **Verify your environment** with the capability self-test:
   ```bash
   <skill45video-python> agent/check_tools.py --story stories/ram_riya.story.yaml
   ```
   Aim for `== ALL PASS ==`. For the live-MCP path, also run the 3 MCP probes in
   [`agent/AGENT_PLAYBOOK.md`](agent/AGENT_PLAYBOOK.md) (Stage 0).

## How to verify a change end-to-end
The fastest smoke test is the worked example through all four stages of the
[Agent Playbook](agent/AGENT_PLAYBOOK.md): `voices` → `mcp_studio.build_story` (over the MCP) → `mux`.
You should get `out/ram_riya.mp4` (~14–15s, video+audio, with the end card). For the subprocess
pipeline, render a single shot: `python build_scene.py <scene> --only <shot_id>`.

## Coding conventions
- **Python**: follow the surrounding style — module docstring explaining *why*, descriptive names,
  comments only where intent isn't obvious. Match the existing comment density; don't over-comment.
- **Encapsulate gotchas, don't re-derive them.** If you hit a Blender/ffmpeg trap, fix it inside the
  helper and add a one-line `# GOTCHA:` note (see `agent/mcp_studio.py` and `docs/ARCHITECTURE.md §5`).
- **No hardcoded absolute / user-specific paths.** Use relative paths, `Path(__file__)`, `Path.home()`,
  the `SKILL45_*` env vars, or a documented `<ANIM_STUDIO>` placeholder in docs.
- **Two-env boundary**: code under `studiolib/` and `mcp_studio.py` runs inside **Blender's** Python
  (stdlib + bpy only — no PyYAML); `build_scene.py` / `voices.py` / `assemble_story.py` run in the
  **skill45video** env. Don't import across that line.
- Keep diagrams (`README.md`, `docs/ARCHITECTURE.md`) in sync when you change the flow.
- Syntax-check before pushing: `python -m py_compile <files>`.

## Pull requests
- One focused change per PR; describe what and why, and how you verified it.
- Update the relevant doc/diagram in the same PR.
- Note any new third-party dependency and its license in the README Acknowledgements table.

## Reporting issues
Include: OS, Blender version, which pipeline (subprocess vs live-MCP), the command you ran, and the
full error output. For render/voice issues, the output of `agent/check_tools.py` helps a lot.
