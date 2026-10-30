#!/usr/bin/env python3
"""VoxCPM2 TTS runner (hf:openbmb/VoxCPM2@32279eff, Apache-2.0). Runs in its own venv; denoiser off.

--ref: a reference clip to clone (only voices you made or may use). --ref-text: what it says (better match).
Only the words are spoken: <tags>, (style) and [stage] notes are removed first (they would be read aloud). Writes 16-bit PCM WAV at the model's rate (48 kHz)."""
import argparse, os, random, re
from pathlib import Path

import numpy as np, soundfile as sf, torch
from voxcpm import VoxCPM

ap = argparse.ArgumentParser()
ap.add_argument("--text", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--ref"); ap.add_argument("--ref-text", default="")
ap.add_argument("--cfg", type=float, default=2.0); ap.add_argument("--steps", type=int, default=10)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--model-dir", default=os.environ.get("OPENSOUL_VOXCPM2_DIR",
                                                      str(Path.home() / "OpenSoul/models/voxcpm2")))
a = ap.parse_args()
random.seed(a.seed); np.random.seed(a.seed); torch.manual_seed(a.seed)
src = a.model_dir if (Path(a.model_dir) / "model.safetensors").is_file() else "openbmb/VoxCPM2"
m = VoxCPM.from_pretrained(src, load_denoiser=False, optimize=False)  # no torch.compile (aarch64 GB10)
text = re.sub(r"<\s*/?\s*[A-Za-z][^<>]*>|\([^()]*\)|\[[^\[\]]*\]", " ", a.text)
text = re.sub(r"\s+([,.!?;:])", r"\1", re.sub(r"\s+", " ", text)).strip()
kw = {"text": text, "cfg_value": a.cfg, "inference_timesteps": a.steps}
if a.ref:
    kw["reference_wav_path"] = a.ref
    if a.ref_text:  # transcript given: also use the clip as the continuation prompt
        kw.update(prompt_wav_path=a.ref, prompt_text=a.ref_text)
wav = m.generate(**kw)
sr = getattr(getattr(m, "tts_model", None), "sample_rate", 48000)
sf.write(a.out, np.asarray(wav, dtype=np.float32), sr, subtype="PCM_16")
print("wrote", a.out, sr)
