"""check_tools — Stage-0 capability self-test for the story pipeline. RUN WITH THE skill45video PYTHON.

Tells you up front whether THIS host can run the shell stages (voices + mux): conda envs, ffmpeg,
the Blender exe, and the assets a story needs. Prints PASS/FAIL per check and exits non-zero on any
failure, so an agent can gate on it.

It canNOT test the agent's own MCP reachability (whether it can call mcp__blender__*) — that lives in
a different process. Run the 3 MCP probes from AGENT_PLAYBOOK.md (Stage 0) for that half.

  <skill45video>/python.exe agent/check_tools.py
  <skill45video>/python.exe agent/check_tools.py --story stories/ram_riya.story.yaml
"""
import argparse
import importlib
import os
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                 # noqa: BLE001
    pass

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GENAI_PY = Path(os.environ.get("SKILL45_DOTS_PYTHON")
                or (Path.home() / ".conda" / "envs" / "genai" / "python.exe"))
FFMPEG = Path(os.environ.get("SKILL45_FFMPEG")
              or (Path.home() / ".conda" / "envs" / "skill45video" / "Library" / "bin" / "ffmpeg.exe"))
FFPROBE = Path(os.environ.get("SKILL45_FFPROBE")
               or (Path.home() / ".conda" / "envs" / "skill45video" / "Library" / "bin" / "ffprobe.exe"))
BLENDER = Path(os.environ.get("SKILL45_BLENDER")
               or r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe")

results = []


def check(name, ok, detail=""):
    results.append(ok)
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}{('  — ' + detail) if detail else ''}")
    return ok


def _runs(path, *args):
    try:
        r = subprocess.run([str(path), *args], capture_output=True, text=True, timeout=30)
        return r.returncode == 0, (r.stdout or r.stderr).splitlines()[0] if (r.stdout or r.stderr) else ""
    except Exception as e:                        # noqa: BLE001
        return False, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", default=None, help="also check the assets a specific story needs")
    a = ap.parse_args()

    print("== anim-studio story pipeline — capability check ==\n")

    print("Python packages (skill45video env):")
    for mod in ["numpy", "scipy", "soundfile", "yaml"]:
        try:
            importlib.import_module(mod)
            check(f"import {mod}", True)
        except Exception as e:                    # noqa: BLE001
            check(f"import {mod}", False, str(e))

    print("\nBinaries:")
    ok, ver = _runs(FFMPEG, "-version"); check(f"ffmpeg ({FFMPEG.name})", ok, ver)
    ok, ver = _runs(FFPROBE, "-version"); check(f"ffprobe ({FFPROBE.name})", ok, ver)
    check(f"genai python ({GENAI_PY})", GENAI_PY.exists(), "dots.tts voice env")
    check(f"Blender exe ({BLENDER.name})", BLENDER.exists(),
          "the agent drives this live over the MCP — exe presence is informational")

    print("\nReused project files:")
    for rel in ["voices.py", "make_voice.py", "agent/mcp_studio.py", "agent/assemble_story.py",
                "../skill45-video/thumbnail.py"]:
        p = (ROOT / rel).resolve()
        check(rel, p.exists())

    if a.story:
        print(f"\nStory assets ({a.story}):")
        import yaml
        story = yaml.safe_load((ROOT / a.story).read_text(encoding="utf-8")) \
            if not Path(a.story).is_absolute() else yaml.safe_load(Path(a.story).read_text(encoding="utf-8"))
        bg = story.get("background") or {}
        if bg.get("hdri"):
            hp = ROOT / bg["hdri"]
            check(f"hdri {bg['hdri']}", hp.exists())
        for who, c in story["characters"].items():
            bp = ROOT / c["blend"]
            fj = bp.with_suffix(".face.json")
            check(f"{who}: {c['blend']}", bp.exists())
            check(f"{who}: {fj.name}", fj.exists(), "face metadata sidecar")

    ok = all(results)
    print(f"\n== {'ALL PASS' if ok else 'SOME CHECKS FAILED'} ({sum(results)}/{len(results)}) ==")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
