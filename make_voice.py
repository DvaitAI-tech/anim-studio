"""Generate dots.tts voice lines (NK's cloned voice) for anim-studio. Run with the genai python.

Single line:
  <genai>/python.exe make_voice.py --text "..." --ref <nk_en.wav> --lang en --out voice/line.wav
Batch (ONE model load for many lines — preferred when a scene has several dots lines):
  <genai>/python.exe make_voice.py --jobs jobs.json --ref <nk_hi.wav> --lang hi
  # jobs.json = [{"text": "...", "out": "voice/l1.wav"}, {"text": "...", "out": "voice/l2.wav"}]

Applies the same trim + loudness-normalize we use in skill45-video so the clip starts on the
voice and sits at a consistent level (dots is a raw AR model — see dots-tts-voice-pilot notes).
"""
import argparse
import json
import os

import numpy as np
import soundfile as sf
import torch

from dots_tts.runtime import DotsTtsRuntime

_DEF_MODEL = r"C:\Users\ZENITHRA_MK\Music\NK\Projects\dots-pilot\models\dots.tts-soar"


def postprocess(audio, sr, target_rms=0.10, peak=0.97, pad_ms=60):
    a = np.asarray(audio, dtype=np.float32).reshape(-1)
    if a.size == 0:
        return a
    pk = float(np.abs(a).max())
    if pk < 1e-5:
        return a
    idx = np.where(np.abs(a) > 0.02 * pk)[0]
    if idx.size:
        pad = int(sr * pad_ms / 1000)
        a = a[max(0, idx[0] - pad): min(len(a), idx[-1] + pad + 1)]
    rms = float(np.sqrt(np.mean(a ** 2)))
    if rms > 1e-5:
        a = a * min(target_rms / rms, peak / max(float(np.abs(a).max()), 1e-5))
    return a.astype(np.float32)


def _gen_one(rt, text, ref, language, steps, out):
    r = rt.generate(text=text, prompt_audio_path=ref, language=language, num_steps=steps)
    audio = postprocess(r["audio"].float().cpu().squeeze().numpy(), r["sample_rate"])
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    sf.write(out, audio, r["sample_rate"])
    print(f"VOICE_OUT {out} {len(audio)/r['sample_rate']:.2f}s sr={r['sample_rate']}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", help="single-line mode: the text")
    ap.add_argument("--out", help="single-line mode: output wav")
    ap.add_argument("--jobs", help="batch mode: JSON list of {text, out}")
    ap.add_argument("--ref", required=True, help="reference voice clip (nk_en.wav / nk_hi.wav)")
    ap.add_argument("--lang", default="en", choices=["en", "hi"])
    ap.add_argument("--steps", type=int, default=16)
    ap.add_argument("--model", default=_DEF_MODEL)
    a = ap.parse_args()

    torch.set_grad_enabled(False)
    rt = DotsTtsRuntime.from_pretrained(a.model, precision="bfloat16", optimize=False)
    language = "EN" if a.lang == "en" else "auto_detect"

    if a.jobs:
        jobs = json.loads(open(a.jobs, encoding="utf-8").read())
        for j in jobs:
            _gen_one(rt, j["text"], a.ref, language, a.steps, j["out"])
    else:
        if not (a.text and a.out):
            raise SystemExit("need --text and --out (single mode) or --jobs (batch mode)")
        _gen_one(rt, a.text, a.ref, language, a.steps, a.out)


if __name__ == "__main__":
    main()
