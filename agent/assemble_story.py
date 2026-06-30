"""assemble_story — host side of the live-MCP story pipeline. RUN WITH THE skill45video PYTHON.

Two stages bracket the Blender step (mcp_studio.build_story, run by the agent over the MCP):

  voices <story.yaml>   stage 2: synth every dialogue line (dots/orpheus), compute per-line
                        amplitude envelopes + dialogue offsets, and write ONE self-contained
                        voice/<title>/manifest.json that the Blender step consumes.

  mux <story.yaml>      stage 4: take the silent render out/<title>.silent.mp4 + the manifest,
                        lay each voice line at its offset (ffmpeg adelay+amix), append the
                        Skill45 end card with a fade, and write the final out/<title>.mp4.

Reuses voices.synth_dots / synth_orpheus / extract_envelope (and the same dots-subprocess +
orpheus-in-proc routing) and skill45-video/thumbnail.py for the brand end card. The story.yaml
schema is documented in agent/story.schema.md.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # anim-studio/ root for voices.py
import voices  # reuse synth + envelope + ffprobe duration

try:
    sys.stdout.reconfigure(encoding="utf-8")     # Devanagari lines -> non-UTF8 Windows console
except Exception:                                # noqa: BLE001
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                               # anim-studio/
SKILL45_VIDEO = ROOT.parent / "skill45-video"
FFMPEG = Path(os.environ.get("SKILL45_FFMPEG")
              or (Path.home() / ".conda" / "envs" / "skill45video" / "Library" / "bin" / "ffmpeg.exe"))
FFPROBE = voices.FFPROBE

LEAD = 0.3        # silence before the first line (s)
GAP = 0.35       # silence between consecutive lines (s)
TAIL_FRAMES = 10  # hold after the last line before the render ends


def _abs(p):
    """Resolve a story path relative to anim-studio/ unless already absolute."""
    p = Path(p)
    return str(p if p.is_absolute() else (ROOT / p))


def _face_json_for(blend_path):
    """Sidecar face metadata lives beside the blend: <stem>.face.json."""
    return str(Path(blend_path).with_suffix(".face.json"))


# ----------------------------------------------------------------------------- stage 2: voices
def stage_voices(story_path):
    story = yaml.safe_load(Path(story_path).read_text(encoding="utf-8"))
    title = story["title"]
    fps = int(story.get("fps", 30))
    out_dir = ROOT / "voice" / title
    out_dir.mkdir(parents=True, exist_ok=True)

    chars = story["characters"]
    lines = []
    for d in story["dialogue"]:
        who = d["who"]
        lines.append({"idx": len(lines), "who": who, "shot": "story",
                      "text": d["line"], "voice": dict(chars[who]["voice"])})

    # per-line cache (skip re-synth when text unchanged) — same contract as voices.synth_scene
    todo = []
    for ln in lines:
        wav = out_dir / f"{ln['idx']:02d}_{ln['who']}.wav"
        txt = wav.with_suffix(".txt")
        if wav.exists() and txt.exists() and txt.read_text(encoding="utf-8") == ln["text"]:
            continue
        todo.append(ln)
    if todo:
        voices.synth_dots([l for l in todo if l["voice"]["engine"] == "dots"], out_dir)
        voices.synth_orpheus([l for l in todo if l["voice"]["engine"] == "orpheus"], out_dir)
        for ln in todo:
            (out_dir / f"{ln['idx']:02d}_{ln['who']}.wav").with_suffix(".txt").write_text(
                ln["text"], encoding="utf-8")
    else:
        print("[cache] all lines up to date — nothing to synth", flush=True)

    # per-line dur + envelope + cumulative offsets
    manifest_lines = []
    offset = LEAD
    for ln in lines:
        wav = out_dir / f"{ln['idx']:02d}_{ln['who']}.wav"
        dur = round(voices._dur(wav), 3)
        env = voices.extract_envelope(wav, fps)
        frame_start = round(offset * fps) + 1
        manifest_lines.append({
            "idx": ln["idx"], "who": ln["who"], "text": ln["text"],
            "wav": str(wav), "dur": dur, "offset": round(offset, 3),
            "frame_start": frame_start, "frame_end": frame_start + len(env),
            "env": env,
        })
        print(f"  [{ln['idx']:02d}] {ln['who']:5s} {dur:5.2f}s @ {offset:5.2f}s  "
              f"frames={len(env)}  {ln['text'][:42]}", flush=True)
        offset += dur + GAP

    last = manifest_lines[-1]
    frame_end = round((last["offset"] + last["dur"]) * fps) + TAIL_FRAMES

    bg = story.get("background") or {}
    manifest = {
        "title": title, "fps": fps, "aspect": story.get("aspect", "16x9"),
        "out_silent": _abs(f"out/{title}.silent.mp4"),
        "background": {"hdri": _abs(bg["hdri"]) if bg.get("hdri") else None,
                       "strength": bg.get("strength", 1.0)},
        "characters": {who: {"blend": _abs(c["blend"]), "prefix": f"{who}_",
                             "x": c["x"], "face": c.get("face", 0),
                             "face_json": _abs(_face_json_for(c["blend"]))}
                       for who, c in chars.items()},
        "props": story.get("props", []),
        "endcard": story.get("endcard", {"seconds": 3, "source": "skill45"}),
        "lines": manifest_lines,
        "frame_end": frame_end,
    }
    mpath = out_dir / "manifest.json"
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[voices] manifest -> {mpath}")
    print(f"[voices] {len(manifest_lines)} lines, frame_end={frame_end} "
          f"(~{frame_end / fps:.1f}s @ {fps}fps)")
    print("[next] run the Blender step (mcp_studio.build_story) with this manifest, then `mux`.")
    return manifest


# ----------------------------------------------------------------------------- stage 4: assemble
def _make_endcard(title, source):
    """Skill45 brand card via skill45-video/thumbnail.py, or pass through a given png path."""
    if source and source != "skill45":
        return _abs(source)
    png = ROOT / "out" / f"{title}.endcard.png"
    cmd = [sys.executable, str(SKILL45_VIDEO / "thumbnail.py"), "--out", str(png)]
    subprocess.run(cmd, check=True)
    return str(png)


def stage_mux(story_path):
    story = yaml.safe_load(Path(story_path).read_text(encoding="utf-8"))
    title = story["title"]
    manifest = json.loads((ROOT / "voice" / title / "manifest.json").read_text(encoding="utf-8"))
    fps = manifest["fps"]
    silent = Path(manifest["out_silent"])
    if not silent.exists():
        raise SystemExit(f"[mux] silent render missing: {silent}\n"
                         f"      run the Blender step (mcp_studio.build_story) first.")

    out_dir = ROOT / "out"
    voiced = out_dir / f"{title}.voiced.mp4"
    lines = manifest["lines"]

    # 1) lay each line at its offset: [n:a]adelay=<ms>:all=1[an] ; ...amix=...:normalize=0
    cmd = [str(FFMPEG), "-y", "-i", str(silent)]
    for ln in lines:
        cmd += ["-i", ln["wav"]]
    parts, labels = [], []
    for n, ln in enumerate(lines, start=1):
        ms = int(round(ln["offset"] * 1000))
        parts.append(f"[{n}:a]adelay={ms}:all=1[a{n}]")
        labels.append(f"[a{n}]")
    parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest[dlg]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "0:v", "-map", "[dlg]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(voiced)]
    subprocess.run(cmd, check=True)

    # 2) append the end card with a 0.5s fade-in (silent audio so the streams concat cleanly)
    ec = story.get("endcard", {}) or {}
    secs = float(ec.get("seconds", 3))
    card = _make_endcard(title, ec.get("source", "skill45"))
    final = out_dir / f"{title}.mp4"
    cmd = [str(FFMPEG), "-y", "-i", str(voiced),
           "-loop", "1", "-t", str(secs), "-i", card,
           "-f", "lavfi", "-t", str(secs), "-i", "anullsrc=r=48000:cl=mono",
           "-filter_complex",
           "[1:v]scale=1280:720,fps=%d,setsar=1,format=yuv420p,fade=t=in:st=0:d=0.5[card];"
           "[0:v]setsar=1,format=yuv420p[main];"
           "[main][card]concat=n=2:v=1:a=0[v];[0:a][2:a]concat=n=2:v=0:a=1[a]" % fps,
           "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "20",
           "-pix_fmt", "yuv420p", "-c:a", "aac", str(final)]
    subprocess.run(cmd, check=True)

    dur = voices._dur(final)
    print(f"\n[mux] FINAL -> {final}  ({dur:.2f}s)")
    return str(final)


def main():
    ap = argparse.ArgumentParser(description="anim-studio story pipeline (host stages).")
    ap.add_argument("stage", choices=["voices", "mux"])
    ap.add_argument("story", help="path to a *.story.yaml")
    a = ap.parse_args()
    if a.stage == "voices":
        stage_voices(a.story)
    else:
        stage_mux(a.story)


if __name__ == "__main__":
    main()
