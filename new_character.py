"""new_character.py — the AGENT-facing front door to Component 1.

An agent (or NK) picks building blocks from catalog.yaml and this writes a character recipe
(characters/<name>/character.yaml). With --build it then bakes the asset via build_character.py.
Run with the skill45video python (it has pyyaml).

  # see what's available to pick from
  python new_character.py --list

  # generate a recipe (and optionally build it right away)
  python new_character.py --name riya --body female_base --outfit skirt_warm --skin light \
      --voice ritika_hindi --build

The agent loop: list options -> choose -> generate YAML -> build -> read validation + preview.png ->
self-correct (edit recipe / re-pick) -> rebuild. Deterministic and headless.
"""
import argparse
import subprocess
import sys
from pathlib import Path

import yaml

try:                                   # so printing non-ASCII (e.g. Devanagari voice names) never crashes
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "catalog.yaml"


def load_catalog():
    return yaml.safe_load(CATALOG.read_text(encoding="utf-8"))


def _resolve_color(value, named):
    """Accept a catalog key, an [r,g,b] list, or an 'r,g,b' string -> [r,g,b]."""
    if value is None:
        return None
    if isinstance(value, str):
        if value in named:
            return named[value]
        if "," in value:
            return [float(x) for x in value.split(",")]
        raise SystemExit(f"unknown color/skin '{value}' (known: {sorted(named)} or 'r,g,b')")
    return list(value)


def make_recipe(name, body, outfit=None, skin=None, height=None, voice=None,
                forward="+Y", textured=False, catalog=None):
    """Build a character-recipe dict from catalog choices. Pure (no file I/O)."""
    cat = catalog or load_catalog()
    if body not in cat["bodies"]:
        raise SystemExit(f"unknown body '{body}' (known: {sorted(cat['bodies'])})")
    b = cat["bodies"][body]
    textured = textured or bool(b.get("textured"))   # a clothed/anime body keeps its own materials
    if b.get("forward"):
        forward = b["forward"]

    look = {}
    if textured:
        look["textured"] = True
    else:
        look["skin"] = _resolve_color(skin, cat.get("skins", {})) or [0.80, 0.62, 0.50]
        if outfit:
            if outfit not in cat["outfits"]:
                raise SystemExit(f"unknown outfit '{outfit}' (known: {sorted(cat['outfits'])})")
            o = dict(cat["outfits"][outfit])
            o.pop("desc", None)
            if o.get("mesh"):
                look["garment"] = o["mesh"]      # a real garment mesh bound to the rig (change-clothes)
                if o.get("oversize"):
                    look["garment_oversize"] = o["oversize"]
            else:
                look["clothes"] = o              # painted skin/shirt/lower regions

    if isinstance(voice, str):
        if voice not in cat.get("voices", {}):
            raise SystemExit(f"unknown voice '{voice}' (known: {sorted(cat.get('voices', {}))})")
        voice = cat["voices"][voice]

    recipe = {"name": name, "source": b["source"],
              "target_height": float(height) if height else b.get("height", 1.7),
              "forward": forward, "rig": "auto", "look": look}
    if voice:
        recipe["voice"] = voice
    return recipe


def write_recipe(recipe):
    """Write characters/<name>/character.yaml; returns its path."""
    outdir = HERE / "characters" / recipe["name"]
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "character.yaml"
    path.write_text(yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def print_catalog():
    cat = load_catalog()
    print("BODIES:")
    for k, v in cat["bodies"].items():
        print(f"  {k:14s} {v.get('desc','')}")
    print("OUTFITS (painted clothing presets):")
    for k, v in cat["outfits"].items():
        print(f"  {k:14s} {v.get('desc','')}")
    print(f"SKINS:  {', '.join(cat.get('skins', {}))}  (or pass r,g,b)")
    print(f"VOICES: {', '.join(cat.get('voices', {}))}")


def main():
    ap = argparse.ArgumentParser(description="Generate (and optionally build) a character recipe.")
    ap.add_argument("--list", action="store_true", help="print the catalog of pickable options and exit")
    ap.add_argument("--name", help="character id (folder name)")
    ap.add_argument("--body", help="a body id from the catalog")
    ap.add_argument("--outfit", help="an outfit id from the catalog (omit for plain skin)")
    ap.add_argument("--skin", help="a skin id, or 'r,g,b'")
    ap.add_argument("--height", type=float, help="override target height (m)")
    ap.add_argument("--voice", help="a voice id from the catalog")
    ap.add_argument("--forward", default="+Y", help="forward axis (+Y|-Y|+X|-X)")
    ap.add_argument("--textured", action="store_true", help="keep the model's own materials (clothed/textured source)")
    ap.add_argument("--build", action="store_true", help="bake the asset after writing the recipe")
    ap.add_argument("--inspect", action="store_true", help="with --build: open the bake in the Blender GUI")
    a = ap.parse_args()

    if a.list:
        print_catalog()
        return
    if not (a.name and a.body):
        raise SystemExit("need --name and --body (or --list). See --help.")

    recipe = make_recipe(a.name, a.body, outfit=a.outfit, skin=a.skin, height=a.height,
                         voice=a.voice, forward=a.forward, textured=a.textured)
    path = write_recipe(recipe)
    print(f"[new_character] wrote {path}")
    print(yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False))

    if a.build:
        cmd = [sys.executable, str(HERE / "build_character.py"), str(path)]
        if a.inspect:
            cmd.append("--inspect")
        raise SystemExit(subprocess.run(cmd).returncode)


if __name__ == "__main__":
    main()
