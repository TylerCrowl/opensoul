#!/usr/bin/env python3
"""Render the demo-video credits card (rules: every model/tool must be named on screen).

Source of truth for names and licenses: the README "Licenses" table. Keep this list in sync.
Usage:
  python scripts/make_credits_card.py [--music "Track - Artist (CC0)"] [--out docs/media/credits] [--seconds 11]
Writes credits_card.png (1920x1080) and credits_card.mp4 (static, silent H.264, 30 fps).
"""
import argparse, os, subprocess
from PIL import Image, ImageDraw, ImageFont

ROWS = [  # (model / tool, used for, license)
    ("ComfyUI", "workflow engine", "GPL-3.0"),
    ("Comfy SDK (comfy-sdk)", "runs every GPU stage", "MIT"),
    ("comfy-api-proxy", "Comfy API, local ComfyUI", "MIT"),
    ("Qwen-Image-Edit-2511 (+ Qwen2.5-VL, Lightning)", "character stills, sheet", "Apache-2.0"),
    ("Qwen3-VL-8B-Instruct", "sheet auto-fix checks", "Apache-2.0"),
    ("Z-Image-Turbo (Tongyi-MAI)", "text-only master", "Apache-2.0"),
    ("Qwen3-4B text encoder (qwen_3_4b)", "master prompt encoder", "Apache-2.0"),
    ("FLUX.1 autoencoder (ae) — Black Forest Labs", "master image decoder", "Apache-2.0"),
    ("LTX-2.5", "video, camera moves", "LTX-2.x Community"),
    ("LTX-2.3 IC-LoRA Union Control", "pose-guided re-perform", "LTX-2 Community"),
    ("DWPose + YOLOX-L (ONNX)", "pose guide for re-perform", "Apache-2.0"),
    ("Gemma 4 12B encoder (LTX-2.5 repack)", "video prompts", "Apache-2.0 / LTX-2 Comm."),
    ("Orpheus TTS 3B + SNAC (Built with Llama)", "voice, emotion tags", "Apache-2.0 / Llama 3.2 Comm. / MIT"),
    ("Kokoro-82M", "voice (alt)", "Apache-2.0"),
    ("Chatterbox", "expressive voice", "MIT (Perth watermark)"),
    ("VoxCPM2", "voice from a character clip", "Apache-2.0"),
    ("LatentSync 1.6 + Whisper tiny (MIT)", "lip-sync", "Apache-2.0 / OpenRAIL++-M"),
    ("InsightFace ArcFace buffalo_l", "optional identity score", "MIT / non-commercial weights"),
    ("MediaPipe face landmarker", "lip-sync mouth tracking", "Apache-2.0"),
    ("hysts anime-face-detector", "lip-sync face finding (drawn faces)", "MIT"),
    ("ACE-Step 1.5 (ACE Studio & StepFun)", "music: songs, vocal stems", "MIT"),
    ("ACE-Step Qwen3 0.6B text encoder (qwen_0.6b_ace15)", "music prompts and lyrics", "Apache-2.0"),
    ("ACE-Step 4B text encoder (qwen_4b_ace15)", "music lyrics and structure", "MIT / Apache-2.0 (Qwen3 base)"),
    ("HeartMuLa-oss-3B", "music: songs (listed, not ready)", "Apache-2.0 (pinned revision)"),
    ("beat_this (CPJKU)", "music: beats and bars", "MIT"),
    ("ffmpeg", "look grade, edit, export", "LGPL / GPL"),
    ("OpenSoul app + identity-gate node pack", "this project", "Apache-2.0"),
]
FOOTER = "Videos made with OpenSoul are AI-generated. Lumi, Mio, Ren and Pixel are AI-generated characters; no real person was used as a reference. Not affiliated with Higgsfield."
INTER = "/usr/share/fonts/truetype/sand-box/google/Inter/Inter-VariableFont_opsz,wght.ttf"
FALLBACK = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

def font(size, weight="Regular"):
    try:
        f = ImageFont.truetype(INTER, size)
        try: f.set_variation_by_name(weight)
        except Exception: pass
        return f
    except OSError:
        return ImageFont.truetype(FALLBACK, size)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--music", default="", help='e.g. "Track Name - Artist (CC0)"; omitted = no soundtrack row')
    ap.add_argument("--out", default="docs/media/credits")
    ap.add_argument("--seconds", type=float, default=11.0)
    a = ap.parse_args()
    rows = ROWS + ([("Music: " + a.music, "soundtrack", "public domain" if "public domain" in a.music.lower() else "CC0")] if a.music else [])
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H), (18, 20, 22))
    d = ImageDraw.Draw(img)
    title, head, body, small = font(56, "Bold"), font(28, "SemiBold"), font(30), font(28)
    d.text((120, 70), "OpenSoul runs on open models and tools", font=title, fill=(240, 240, 235))
    d.text((120, 145), "Licenses and sources: README, Licenses table", font=small, fill=(150, 160, 165))
    cols = [120, 930, 1390]
    y = 215
    for x, t in zip(cols, ("Model / tool", "Used for", "License")):
        d.text((x, y), t, font=head, fill=(232, 178, 80))
    y += 46
    d.line((120, y, W - 120, y), fill=(70, 75, 80), width=2)
    y += 14
    step = (H - 150 - y) // len(rows)
    bs = max(16, min(30, step - 5))  # the font follows the row count so rows never overlap
    body = font(bs)
    for i, (n, u, l) in enumerate(rows):
        if i % 2: d.rectangle((110, y - 3, W - 110, y + step - 3), fill=(26, 29, 32))
        lf = body
        while d.textlength(l, font=lf) > W - 120 - cols[2] and lf.size > bs - 8: lf = font(lf.size - 1)
        nf = body
        while d.textlength(n, font=nf) > cols[1] - cols[0] - 30 and nf.size > bs - 8: nf = font(nf.size - 1)
        d.text((cols[0], y), n, font=nf, fill=(235, 235, 230))
        uf = body
        while d.textlength(u, font=uf) > cols[2] - cols[1] - 30 and uf.size > bs - 8: uf = font(uf.size - 1)
        for txt, f_, lim in ((n, nf, cols[1] - cols[0] - 20), (u, uf, cols[2] - cols[1] - 20), (l, lf, W - 110 - cols[2])):
            if d.textlength(txt, font=f_) > lim: print("WARN overflow:", txt)
        d.text((cols[1], y), u, font=uf, fill=(190, 195, 198))
        d.text((cols[2], y), l, font=lf, fill=(190, 195, 198))
        y += step
    d.text((120, H - 100), FOOTER, font=small, fill=(150, 160, 165))
    os.makedirs(a.out, exist_ok=True)
    png = os.path.join(a.out, "credits_card.png"); img.save(png, optimize=True)
    mp4 = os.path.join(a.out, "credits_card.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", png, "-t", str(a.seconds),
                    "-r", "30", "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-crf", "18", mp4], check=True)
    print(png, mp4, "music set" if a.music else "no soundtrack row")

if __name__ == "__main__":
    main()
