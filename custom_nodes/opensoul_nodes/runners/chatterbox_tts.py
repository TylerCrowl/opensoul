#!/usr/bin/env python3
"""Chatterbox TTS runner (official ResembleAI/chatterbox weights). Writes 16-bit PCM WAV."""
import argparse, os, random, numpy as np, soundfile as sf, torch
from pathlib import Path
from chatterbox.tts import ChatterboxTTS

ap = argparse.ArgumentParser()
ap.add_argument("--text", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--ref"); ap.add_argument("--exaggeration", type=float, default=0.5)
ap.add_argument("--cfg-weight", type=float, default=0.5); ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()
random.seed(a.seed); np.random.seed(a.seed); torch.manual_seed(a.seed)
dev = "cuda" if torch.cuda.is_available() else "cpu"
# download_models.sh pre-fetches the weights to $OPENSOUL_HOME/models/chatterbox; use them when present
# (works offline), else fall back to the Hub cache like upstream.
local = Path(os.environ.get("OPENSOUL_CHATTERBOX_DIR", Path(os.environ.get("OPENSOUL_HOME", Path.home() / "OpenSoul")) / "models/chatterbox"))
m = ChatterboxTTS.from_local(str(local), device=dev) if (local / "t3_cfg.safetensors").is_file() else ChatterboxTTS.from_pretrained(device=dev)
wav = m.generate(a.text, audio_prompt_path=a.ref, exaggeration=a.exaggeration, cfg_weight=a.cfg_weight)
sf.write(a.out, wav.squeeze(0).cpu().numpy(), m.sr, subtype="PCM_16")
print("wrote", a.out, m.sr)
