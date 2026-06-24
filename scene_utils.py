"""Shared scene loading for anim-studio (skill45video env): parse a *.scene.yaml and resolve any
`use: <character>` cast entries against built character recipes in characters/<name>/.

Both build_scene.py and voices.py load the scene independently, so this lives in one place they share.
"""
import os
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent


def _load_recipe(name):
    """characters/<name>/character.yaml (preferred) or character.resolved.yaml -> dict, or None."""
    base = HERE / "characters" / name
    for fn in ("character.yaml", "character.resolved.yaml"):
        p = base / fn
        if p.exists():
            return yaml.safe_load(p.read_text(encoding="utf-8"))
    return None


def resolve_cast(scene):
    """For each cast member with `use: <name>`, fill model/color/clothes/voice from the character
    recipe (any inline key on the cast entry wins), and attach the baked `blend` path if it exists."""
    for who, entry in (scene.get("cast") or {}).items():
        use = entry.get("use")
        if not use:
            continue
        rec = _load_recipe(use)
        if not rec:
            raise SystemExit(f"[scene] cast '{who}' uses character '{use}' but "
                             f"characters/{use}/character.yaml was not found")
        look = rec.get("look", {})
        for key, val in (("model", rec.get("source")), ("color", look.get("skin")),
                         ("clothes", look.get("clothes")), ("voice", rec.get("voice"))):
            if key not in entry and val is not None:
                entry[key] = val
        blend = HERE / "characters" / use / "character.blend"
        if blend.exists():
            entry["blend"] = str(blend.resolve())
    return scene


def load_scene(path):
    """Load a scene YAML and resolve `use:` characters."""
    scene = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return resolve_cast(scene)
