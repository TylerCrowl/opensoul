#!/usr/bin/env python3
"""Kokoro-82M TTS from locally downloaded official weights (hexgrad/Kokoro-82M). CPU is plenty."""
import argparse, numpy as np, soundfile as sf, torch
from kokoro import KModel, KPipeline

ap = argparse.ArgumentParser()
ap.add_argument("--model-dir", required=True)
ap.add_argument("--voice", default="am_michael")
ap.add_argument("--speed", type=float, default=1.0)
ap.add_argument("--text", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()
model = KModel(repo_id="hexgrad/Kokoro-82M", config=f"{a.model_dir}/config.json", model=f"{a.model_dir}/kokoro-v1_0.pth").eval()
pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", model=model)
voice = torch.load(f"{a.model_dir}/voices/{a.voice}.pt", weights_only=True)
chunks = [r.audio.numpy() for r in pipe(a.text, voice=voice, speed=a.speed)]
audio = np.concatenate(chunks)
sf.write(a.out, audio, 24000)
print("wrote", a.out, "%.2fs" % (len(audio) / 24000))
