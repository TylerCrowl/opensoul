#!/usr/bin/env python3
"""Orpheus TTS runner: canopylabs/orpheus-3b-0.1-ft as a Q4_K_M GGUF on llama.cpp + SNAC 24 kHz decoder.

Runs on CPU (about 5x slower than real time on 8 cores) or GPU (llama.cpp built with CUDA). Writes 16-bit PCM WAV.
Emotion tags (<laugh> <chuckle> <sigh> <gasp> <cough> <sniffle> <groan> <yawn>) go inline in --text.
Built with Llama: Orpheus is fine-tuned from Meta Llama 3.2 3B (see docs/MODEL_STACK.md).
"""
import argparse, os, sys
from pathlib import Path

import importlib.util  # noqa: E402

# opensoul/orpheus.py is pure Python; load it by path so this venv doesn't need the app's dependencies.
_spec = importlib.util.spec_from_file_location("opensoul_orpheus", Path(__file__).resolve().parents[3] / "opensoul" / "orpheus.py")
orp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(orp)

ap = argparse.ArgumentParser()
ap.add_argument("--text", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--voice", default=orp.DEFAULT_VOICE); ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--temperature", type=float, default=0.6); ap.add_argument("--top-p", type=float, default=0.9)
ap.add_argument("--repetition-penalty", type=float, default=1.1)  # Orpheus needs >= 1.1 to stay stable
ap.add_argument("--max-tokens", type=int, default=2400)            # ~28 s of audio
ap.add_argument("--gguf"); ap.add_argument("--threads", type=int, default=os.cpu_count() or 4)
a = ap.parse_args()

import numpy as np, soundfile as sf, torch  # noqa: E402,E401
from llama_cpp import Llama  # noqa: E402
from snac import SNAC  # noqa: E402

home = Path(os.environ.get("OPENSOUL_HOME", Path.home() / "OpenSoul"))
gguf = a.gguf or os.environ.get("OPENSOUL_ORPHEUS_GGUF") or str(home / "models/orpheus/Orpheus-3b-FT-Q4_K_M.gguf")
snac_dir = Path(os.environ.get("OPENSOUL_SNAC_DIR", home / "models/snac_24khz"))
torch.set_num_threads(a.threads)
llm = Llama(gguf, n_ctx=4096, n_threads=a.threads, n_gpu_layers=-1, seed=a.seed, verbose=False)
snac = (SNAC.from_pretrained(str(snac_dir)) if (snac_dir / "config.json").is_file() else SNAC.from_pretrained("hubertsiuzdak/snac_24khz")).eval()

ids = orp.wrap_prompt(llm.tokenize(orp.prompt_text(a.text, a.voice).encode(), add_bos=True, special=True))
gen = []
for t in llm.generate(ids, temp=a.temperature, top_p=a.top_p, top_k=40, repeat_penalty=a.repetition_penalty):
    if t in (orp.END_SPEECH, orp.END_TEXT) or len(gen) >= a.max_tokens:
        break
    gen.append(t)
codes = orp.audio_codes(gen)
if not codes:
    sys.exit("Orpheus produced no audio codes; try another --seed")
l1, l2, l3 = orp.snac_layers(codes)
with torch.no_grad():
    wav = snac.decode([torch.tensor([l1]), torch.tensor([l2]), torch.tensor([l3])]).squeeze().numpy()
sf.write(a.out, np.clip(wav, -1, 1), orp.SAMPLE_RATE, subtype="PCM_16")
print("wrote", a.out, orp.SAMPLE_RATE, f"{len(wav) / orp.SAMPLE_RATE:.2f}s")
