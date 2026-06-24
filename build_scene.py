"""Orchestrate a *.scene.yaml into a stitched, voiced video (9:16 + 16:9). RUN WITH skill45video PYTHON.

  <skill45video>/python.exe build_scene.py stories/upgrade.opening.scene.yaml

Pipeline (mirrors skill45-video's schema->render->voice->mux, in 3D):
  1. voices.synth_scene  -> per-line wavs + durations (Orpheus ऋतिका / dots router)
  2. compute each shot's duration (explicit `seconds`, else from its dialogue) -> frame counts
  3. per shot x aspect: write a shot-spec JSON -> Blender headless shot-mode -> silent shot mp4
  4. per aspect: concat shots; lay each dialogue line at its global offset (+ optional music); mux
  5. write an SRT sidecar from line offsets
Output: out/<scene>.<aspect>.mp4  (+ .srt)
"""
import argparse
import json
import os
import subprocess
from pathlib import Path

import yaml

import scene_utils  # same dir; load_scene() resolves `use:` characters
import voices  # same dir; provides synth_scene + ffprobe path

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
BLENDER = Path(os.environ.get("SKILL45_BLENDER")
               or r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe")
FFMPEG = Path(os.environ.get("SKILL45_FFMPEG")
              or (Path.home() / ".conda" / "envs" / "skill45video" / "Library" / "bin" / "ffmpeg.exe"))

LEAD = 0.3        # silence before a shot's first line
GAP = 0.35        # gap between consecutive lines in a shot
MIN_SHOT = 2.5    # floor for a shot with no explicit seconds


def shot_layout(shot, line_dur):
    """Return (shot_seconds, [(line_idx, offset_within_shot)]) for the shot's dialogue."""
    lines = shot.get("dialogue") or []
    layout, t = [], LEAD
    for d in lines:
        idx = d["_idx"]
        layout.append((idx, t))
        t += line_dur[idx] + GAP
    explicit = shot.get("seconds")
    secs = float(explicit) if explicit else max(MIN_SHOT, t + LEAD - GAP)
    return secs, layout


def tag_dialogue_indices(scene):
    """Number dialogue lines in the same order voices.collect_lines does, so indices line up."""
    i = 0
    for shot in scene["shots"]:
        for d in shot.get("dialogue") or []:
            d["_idx"] = i
            i += 1


def _cast_spec(scene, c):
    """Build one shot-cast entry: resolve model + the motion clip for its action.

    Motion source priority:
      1. scene `motion_library` + `motion_map` -> "<lib>#<ClipName>" (Quaternius multi-clip file)
      2. assets/motions/<action>.fbx           -> one clip per file (Mixamo style)
      3. none                                   -> render falls back to the model's built-in clip
    """
    action = c.get("action", "")
    entry = {"who": c["who"], "model": str((ASSETS / scene["cast"][c["who"]]["model"]).resolve()),
             "at": c["at"], "action": action}
    if c.get("to"):
        entry["to"] = c["to"]
    color = scene["cast"][c["who"]].get("color")
    if color:
        entry["color"] = color
    clothes = scene["cast"][c["who"]].get("clothes")
    if clothes:
        entry["clothes"] = clothes
    blend = scene["cast"][c["who"]].get("blend")
    if blend:
        entry["blend"] = blend   # baked character.blend (renderer links it; else imports `model`)

    lib = scene.get("motion_library")
    mmap = scene.get("motion_map", {})
    per_file = ASSETS / "motions" / f"{action}.fbx"
    if lib and action in mmap:
        entry["motion"] = f"{(ASSETS / lib).resolve()}#{mmap[action]}"
    elif action and per_file.exists():
        entry["motion"] = str(per_file.resolve())
    return entry


def render_shots(scene, manifest, aspect, fps, shots_dir):
    line_dur = {m["idx"]: m["dur"] for m in manifest}
    positions = scene["positions"]
    shot_files, shot_secs = [], []
    for shot in scene["shots"]:
        secs, _ = shot_layout(shot, line_dur)
        shot_secs.append(secs)
        spec = {
            "id": shot["id"], "aspect": aspect, "fps": fps, "frames": round(secs * fps),
            "engine": "eevee", "samples": 48,
            "out": str(shots_dir / f"{shot['id']}.{aspect}.mp4"),
            **({"hdri": str((ASSETS / scene["hdri"]).resolve())} if scene.get("hdri") else {}),
            **({"hdri_strength": scene["hdri_strength"]} if scene.get("hdri_strength") else {}),
            **({"bench": scene["bench"]} if scene.get("bench") else {}),
            "walk_face_offset": scene.get("walk_face_offset", 0),
            "positions": positions,
            "cast": [_cast_spec(scene, c) for c in shot["cast"]],
            "camera": shot.get("camera", {}),
        }
        spec_path = shots_dir / f"spec.{shot['id']}.{aspect}.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        print(f"[render] {shot['id']} {aspect} ({secs:.1f}s / {spec['frames']}f)...", flush=True)
        rc = subprocess.run([str(BLENDER), "--background", "--python", str(HERE / "render_blender.py"),
                             "--", "--shot", str(spec_path)]).returncode
        if rc != 0:
            raise SystemExit(f"[render] Blender failed on {shot['id']} {aspect}")
        shot_files.append(spec["out"])
    return shot_files, shot_secs


def _ts(t):
    h, m, s = int(t // 3600), int((t % 3600) // 60), t % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}".replace(".", ",")


def assemble(scene, manifest, aspect, shot_files, shot_secs, out_stem):
    line_dur = {m["idx"]: m["dur"] for m in manifest}
    line_wav = {m["idx"]: m["wav"] for m in manifest}
    line_text = {m["idx"]: m["text"] for m in manifest}

    # 1) concat shot videos (identical params -> stream copy)
    shots_dir = Path(shot_files[0]).parent
    concat_txt = shots_dir / f"_concat.{aspect}.txt"
    concat_txt.write_text("".join(f"file '{Path(f).as_posix()}'\n" for f in shot_files), encoding="utf-8")
    concat_mp4 = shots_dir / f"_concat.{aspect}.mp4"
    subprocess.run([str(FFMPEG), "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt),
                    "-c", "copy", str(concat_mp4)], check=True)

    # 2) global offset of every line + SRT entries
    placements, srt = [], []
    shot_start = 0.0
    for shot, secs in zip(scene["shots"], shot_secs):
        _, layout = shot_layout(shot, line_dur)
        for idx, off in layout:
            g = shot_start + off
            placements.append((idx, g))
            srt.append((g, g + line_dur[idx], line_text[idx]))
        shot_start += secs

    # 3) build the dialogue track (adelay each line, amix) and mux over the concat video
    out_mp4 = f"{out_stem}.{aspect}.mp4"
    if placements:
        cmd = [str(FFMPEG), "-y", "-i", str(concat_mp4)]
        for idx, _ in placements:
            cmd += ["-i", line_wav[idx]]
        parts, labels = [], []
        for n, (idx, g) in enumerate(placements, start=1):
            ms = int(g * 1000)
            parts.append(f"[{n}:a]adelay={ms}:all=1[a{n}]")
            labels.append(f"[a{n}]")
        parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest[dlg]")
        cmd += ["-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[dlg]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", out_mp4]
        subprocess.run(cmd, check=True)
    else:
        subprocess.run([str(FFMPEG), "-y", "-i", str(concat_mp4), "-c", "copy", out_mp4], check=True)

    # 4) SRT sidecar
    srt_path = f"{out_stem}.{aspect}.srt"
    with open(srt_path, "w", encoding="utf-8") as fh:
        for i, (s, e, txt) in enumerate(sorted(srt), 1):
            fh.write(f"{i}\n{_ts(s)} --> {_ts(e)}\n{txt}\n\n")
    print(f"[assemble] {out_mp4}  (+ {Path(srt_path).name})", flush=True)
    return out_mp4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("--aspects", default=None, help="override, e.g. 16x9 or 16x9,9x16")
    ap.add_argument("--only", default=None, help="render just one shot id (fast verify)")
    a = ap.parse_args()

    scene = scene_utils.load_scene(a.scene)   # parse YAML + resolve `use:` characters
    tag_dialogue_indices(scene)          # global line indices BEFORE filtering (match voice manifest)
    if a.only:
        scene["shots"] = [s for s in scene["shots"] if s["id"] == a.only]
        if not scene["shots"]:
            raise SystemExit(f"--only: no shot named '{a.only}'")
    fps = int(scene.get("fps", 30))
    aspects = (a.aspects.split(",") if a.aspects else scene.get("aspects", ["16x9", "9x16"]))
    stem = Path(a.scene).stem
    out_stem = str(HERE / "out" / stem)
    shots_dir = HERE / "out" / "_shots" / stem
    shots_dir.mkdir(parents=True, exist_ok=True)

    print("[1/3] synthesizing voices...", flush=True)
    manifest = voices.synth_scene(a.scene)

    results = []
    for aspect in aspects:
        print(f"\n[2/3] rendering shots ({aspect})...", flush=True)
        shot_files, shot_secs = render_shots(scene, manifest, aspect, fps, shots_dir)
        print(f"[3/3] assembling ({aspect})...", flush=True)
        results.append(assemble(scene, manifest, aspect, shot_files, shot_secs, out_stem))

    total = 0.0
    for shot in scene["shots"]:
        total += shot_layout(shot, {m["idx"]: m["dur"] for m in manifest})[0]
    print(f"\nDONE ({total:.1f}s):")
    for r in results:
        print(f"  {r}")


if __name__ == "__main__":
    main()
