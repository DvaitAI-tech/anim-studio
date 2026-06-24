"""Voice router for anim-studio scenes. RUN WITH THE skill45video PYTHON.

Per dialogue line, routes to the character's voice engine and produces a wav:
  * engine 'orpheus'  -> in-process via skill45-video/orpheus_mv.py (Hindi female ऋतिका)
  * engine 'dots'     -> batched subprocess to the genai python (anim-studio/make_voice.py), NK's clone

Returns/writes a manifest (order = dialogue order) of {idx, shot, who, engine, text, wav, dur}.
Durations come from ffprobe (format-agnostic). Mirrors how skill45-video already dispatches
orpheus-in-process vs dots-subprocess, so we reuse both as-is.

Standalone (M1.1 verification):
  <skill45video>/python.exe voices.py --scene stories/upgrade.opening.scene.yaml
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

import scene_utils  # same dir; load_scene() resolves `use:` characters

HERE = Path(__file__).resolve().parent
SKILL45_VIDEO = HERE.parent / "skill45-video"
DOTS_PILOT = HERE.parent / "dots-pilot"
GENAI_PY = Path(os.environ.get("SKILL45_DOTS_PYTHON")
                or (Path.home() / ".conda" / "envs" / "genai" / "python.exe"))
FFPROBE = Path(os.environ.get("SKILL45_FFPROBE")
               or (Path.home() / ".conda" / "envs" / "skill45video" / "Library" / "bin" / "ffprobe.exe"))


def _dur(path):
    out = subprocess.run([str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def _resolve_ref(ref):
    p = Path(ref)
    return str(p if p.is_absolute() else (DOTS_PILOT / ref))


def collect_lines(scene):
    """Flatten scene dialogue into ordered line dicts with each speaker's voice spec."""
    cast = scene["cast"]
    lines = []
    for shot in scene["shots"]:
        for d in shot.get("dialogue") or []:
            who = d["who"]
            voice = dict(cast[who]["voice"])
            lines.append({"idx": len(lines), "shot": shot["id"], "who": who,
                          "text": d["line"], "voice": voice})
    return lines


def synth_orpheus(lines, out_dir):
    """In-process ऋतिका synthesis (skill45video env). Writes 24kHz PCM wavs."""
    if not lines:
        return
    sys.path.insert(0, str(SKILL45_VIDEO))
    from orpheus_mv import OrpheusService, clean_devanagari, SR  # noqa: reuse skill45-video
    from scipy.io.wavfile import write as write_wav

    by_voice = {}
    for ln in lines:
        by_voice.setdefault(ln["voice"].get("voice", "ऋतिका"), []).append(ln)
    for voice_id, group in by_voice.items():
        svc = OrpheusService(voice=voice_id, lang="hi")
        for ln in group:
            audio = svc._synthesize(clean_devanagari(ln["text"]))
            write_wav(str(out_dir / f"{ln['idx']:02d}_{ln['who']}.wav"), SR, audio[0])
            print(f"[orpheus] line {ln['idx']} ({ln['who']}) -> {ln['idx']:02d}_{ln['who']}.wav", flush=True)


def synth_dots(lines, out_dir):
    """Batched subprocess to genai make_voice.py — one model load per (lang) group."""
    if not lines:
        return
    by_lang = {}
    for ln in lines:
        by_lang.setdefault(ln["voice"].get("lang", "hi"), []).append(ln)
    for lang, group in by_lang.items():
        ref = _resolve_ref(group[0]["voice"]["ref"])
        jobs = [{"text": ln["text"], "out": str(out_dir / f"{ln['idx']:02d}_{ln['who']}.wav")} for ln in group]
        jobs_path = out_dir / "_dots_jobs.json"
        jobs_path.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")
        cmd = [str(GENAI_PY), str(HERE / "make_voice.py"), "--jobs", str(jobs_path),
               "--ref", ref, "--lang", lang, "--steps", "16"]
        print(f"[dots] {len(group)} line(s), lang={lang}, ref={Path(ref).name} (genai subprocess)...", flush=True)
        env = {**os.environ, "PYTHONUTF8": "1"}
        if subprocess.run(cmd, env=env).returncode != 0:
            raise SystemExit("[dots] make_voice subprocess failed (see output above)")


def synth_scene(scene_path, out_dir=None):
    scene = scene_utils.load_scene(scene_path)   # resolves `use:` characters -> voice specs
    out_dir = Path(out_dir or (HERE / "voice" / Path(scene_path).stem))
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = collect_lines(scene)

    # Per-line cache: skip synth if the wav exists and its sidecar text is unchanged. This avoids
    # reloading the 5 GB dots / Orpheus models on re-runs when only some lines changed.
    todo = []
    for ln in lines:
        wav = out_dir / f"{ln['idx']:02d}_{ln['who']}.wav"
        txt = wav.with_suffix(".txt")
        if wav.exists() and txt.exists() and txt.read_text(encoding="utf-8") == ln["text"]:
            continue
        todo.append(ln)
    if todo:
        synth_dots([l for l in todo if l["voice"]["engine"] == "dots"], out_dir)
        synth_orpheus([l for l in todo if l["voice"]["engine"] == "orpheus"], out_dir)
        for ln in todo:
            (out_dir / f"{ln['idx']:02d}_{ln['who']}.wav").with_suffix(".txt").write_text(
                ln["text"], encoding="utf-8")
    else:
        print("[cache] all lines up to date — nothing to synth", flush=True)

    manifest = []
    for ln in lines:
        wav = out_dir / f"{ln['idx']:02d}_{ln['who']}.wav"
        manifest.append({"idx": ln["idx"], "shot": ln["shot"], "who": ln["who"],
                         "engine": ln["voice"]["engine"], "text": ln["text"],
                         "wav": str(wav), "dur": round(_dur(wav), 3)})
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", required=True)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    manifest = synth_scene(a.scene, a.out)
    print("\n=== VOICE MANIFEST ===")
    for m in manifest:
        print(f"  [{m['idx']:02d}] {m['who']:5s} {m['engine']:8s} {m['dur']:5.2f}s  {m['text'][:48]}")
    print(f"total dialogue: {sum(m['dur'] for m in manifest):.1f}s across {len(manifest)} lines")


if __name__ == "__main__":
    main()
