# `*.story.yaml` — story input for the live-MCP pipeline

One flat, declarative file describes a short multi-character talking scene. It is the **only**
hand-authored input; `assemble_story.py voices` resolves it (synth + offsets) into a self-contained
`voice/<title>/manifest.json`, which the Blender step (`mcp_studio.build_story`) and the `mux` step
both read.

> This is **distinct from `scene.schema.md`**. `scene.yaml` drives the older subprocess pipeline
> (`build_scene.py`, rigged Quaternius/VRM body-motion). `story.yaml` drives the live-MCP path with
> our own primitive `.blend` characters + amplitude lip-sync. They don't mix.

```yaml
title: ram_riya            # output stem -> out/ram_riya.mp4, voice/ram_riya/manifest.json
fps: 30                    # MUST stay 30 (offsets + lip frames are computed at this rate)
aspect: 16x9               # informational; render is 1280x720

background:
  hdri: assets/hdri/residential_garden_2k.hdr   # path under anim-studio/; backdrop + lighting
  strength: 1.0

characters:                # key = role id; becomes the object prefix "<id>_" in Blender
  ram:
    blend: characters/cute_char.blend   # our own character .blend (needs a <stem>.face.json beside it)
    x: -1.05                            # world X position (left negative, right positive)
    face: 22                            # degrees about Z; + turns toward +X. Pair faces each other.
    voice: {engine: dots,    ref: nk_hi.wav, lang: hi}     # dots = NK's cloned voice (genai subprocess)
  riya:
    blend: characters/girl_char.blend
    x: 1.05
    face: -22
    voice: {engine: orpheus, voice: "ऋतिका", lang: hi}     # orpheus = Hindi female (in-process)

props:                     # optional
  - {kind: phone, loc: [0.30, -0.55, 1.05], rot: [-10, 0, 20]}   # Skill45-blue phone between them

dialogue:                  # spoken in order; each line synthesized in its speaker's voice
  - {who: ram,  line: "अरे Riya! इतने ध्यान से क्या देख रही हो?", emotion: neutral}
  - {who: riya, line: "मैं खुद को अपग्रेड कर रही हूँ, Skill45 पर।", emotion: happy}

endcard:                   # optional; defaults to {seconds: 3, source: skill45}
  seconds: 3
  source: skill45          # "skill45" = brand card via skill45-video/thumbnail.py, OR a .png path
```

## Field notes
- **`fps`** — keep 30. Blender otherwise renders 24 and the audio/lip offsets desync (baked-in fix
  forces 30, but the offsets in the manifest are computed against this value).
- **`characters.<id>.blend`** — must be one of our primitive characters with **lips as separate
  `upper_lip`/`lower_lip` objects** and a **`<stem>.face.json`** sidecar (object names + rest-Z +
  open deltas + eye list). See `characters/cute_char.face.json` for the format. The role id becomes
  the Blender object prefix, so two characters never collide.
- **`face`** — degrees about Z. For two characters talking, give the left one a positive angle and
  the right one a negative one so they turn toward each other (e.g. `+22` / `-22`).
- **`voice.engine`** — `dots` (NK's clone, `ref:` a wav under `dots-pilot/`) or `orpheus`
  (`voice:` a name like `ऋतिका`). HI lines are **Hinglish in Devanagari** (transliterate English
  terms: अपग्रेड/स्किल) so Orpheus reads them — per the Skill45 script rules. Avoid em-dashes in
  `dots` lines (the model pauses on them).
- **`emotion`** — carried through the manifest for future expression work; the current amplitude
  lip-sync ignores it (honest limit).

## Timing (computed, not authored)
`assemble_story.py voices` lays lines out as: `LEAD(0.3s)` then each line at the running offset,
advancing by `dur + GAP(0.35s)`. Per line it stores `offset`, `frame_start = round(offset*fps)+1`,
the amplitude `env`, and `dur`. `frame_end = round((last_offset+last_dur)*fps) + 10`.
