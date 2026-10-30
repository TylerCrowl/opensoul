#!/usr/bin/env python3
"""MuseTalk v1.5 lip-sync onto an already-moving clip, without mmpose / face-parsing weights.

Differences from upstream scripts/inference.py (MuseTalk, MIT):
  * face boxes come from OpenCV's bundled Haar cascades (no DWPose/mmcv build needed on ARM64),
    temporally smoothed so the crop does not jitter;
  * the blend mask is a feathered lower-face ellipse instead of the BiSeNet face-parsing model
    (whose weights are only distributed via a Google Drive link, not an official model repo).
Run from the MuseTalk checkout (so `musetalk` imports and ./models resolve).
"""
import argparse, os, subprocess, tempfile, glob, cv2, numpy as np, torch
from PIL import Image, ImageDraw, ImageFilter
from transformers import WhisperModel
from musetalk.utils.utils import load_all_model, datagen
from musetalk.utils.audio_processor import AudioProcessor
from musetalk.utils.blending import get_image


class EllipseMask:
    """Stand-in for FaceParsing: returns a mask of the jaw/mouth region of a face_large crop."""
    def __call__(self, image, mode="jaw"):
        w, h = image.size
        m = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(m)
        # face_large is the face box expanded 1.5x around its centre; mouth/jaw sit in the lower-middle
        d.ellipse([w * 0.26, h * 0.40, w * 0.74, h * 0.80], fill=255)
        return m.filter(ImageFilter.GaussianBlur(max(2, w // 40)))


def detect_boxes(frames, extra_margin):
    cas = [cv2.CascadeClassifier(cv2.data.haarcascades + n) for n in
           ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml", "haarcascade_profileface.xml")]
    raw = []
    for f in frames:
        g = cv2.equalizeHist(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY))
        box = None
        for c in cas:
            r = c.detectMultiScale(g, 1.1, 5, minSize=(48, 48))
            if len(r):
                box = max(r, key=lambda b: b[2] * b[3]); break
        raw.append(box)
    good = [i for i, b in enumerate(raw) if b is not None]
    if not good:
        raise SystemExit("no face found in any frame")
    # fill gaps with nearest detection, then smooth centre and size (EMA forward+backward)
    arr = np.array([raw[min(good, key=lambda j: abs(j - i))] for i in range(len(raw))], dtype=float)
    cx, cy, s = arr[:, 0] + arr[:, 2] / 2, arr[:, 1] + arr[:, 3] / 2, np.maximum(arr[:, 2], arr[:, 3])
    def smooth(v, a=0.3):
        o = v.copy()
        for i in range(1, len(o)): o[i] = a * v[i] + (1 - a) * o[i - 1]
        for i in range(len(o) - 2, -1, -1): o[i] = a * o[i] + (1 - a) * o[i + 1]
        return o
    cx, cy, s = smooth(cx), smooth(cy), smooth(s)
    H, W = frames[0].shape[:2]
    boxes = []
    for x, y, z in zip(cx, cy, s):
        half = z / 2
        x1, x2 = int(max(0, x - half)), int(min(W, x + half))
        y1, y2 = int(max(0, y - half * 0.7)), int(min(H, y + half + extra_margin))
        boxes.append([x1, y1, x2, y2])
    return boxes, len(good)


@torch.no_grad()
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--extra-margin", type=int, default=10)
    a = ap.parse_args()
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    vae, unet, pe = load_all_model(unet_model_path="models/musetalkV15/unet.pth", vae_type="sd-vae",
                                   unet_config="models/musetalkV15/musetalk.json", device=dev)
    pe, vae.vae, unet.model = pe.half().to(dev), vae.vae.half().to(dev), unet.model.half().to(dev)
    ap_ = AudioProcessor(feature_extractor_path="models/whisper")
    whisper = WhisperModel.from_pretrained("models/whisper").to(dev, torch.float16).eval()

    cap = cv2.VideoCapture(a.video); fps = cap.get(cv2.CAP_PROP_FPS); frames = []
    while True:
        ok, f = cap.read()
        if not ok: break
        frames.append(f)
    boxes, n_det = detect_boxes(frames, a.extra_margin)
    print(f"frames={len(frames)} fps={fps} face detected in {n_det}")

    feats, alen = ap_.get_audio_feature(a.audio)
    chunks = ap_.get_whisper_chunk(feats, dev, torch.float16, whisper, alen, fps=fps,
                                   audio_padding_length_left=2, audio_padding_length_right=2)
    lat = [vae.get_latents_for_unet(cv2.resize(f[y1:y2, x1:x2], (256, 256), interpolation=cv2.INTER_LANCZOS4))
           for f, (x1, y1, x2, y2) in zip(frames, boxes)]
    # ping-pong the moving clip if the audio is longer than the video
    fr_c, bx_c, lat_c = frames + frames[::-1], boxes + boxes[::-1], lat + lat[::-1]
    t = torch.tensor([0], device=dev); out = []
    for wb, lb in datagen(chunks, lat_c, a.batch_size, 0, dev):
        pred = unet.model(lb.to(dev, unet.model.dtype), t, encoder_hidden_states=pe(wb.to(dev))).sample
        out.extend(vae.decode_latents(pred))
    fp = EllipseMask(); tmp = tempfile.mkdtemp()
    for i, r in enumerate(out):
        x1, y1, x2, y2 = bx_c[i % len(bx_c)]
        r = cv2.resize(r.astype(np.uint8), (x2 - x1, y2 - y1))
        img = get_image(fr_c[i % len(fr_c)].copy(), r, [x1, y1, x2, y2], mode="jaw", fp=fp)
        cv2.imwrite(f"{tmp}/{i:08d}.png", img)
    ff = os.environ.get("FFMPEG", "ffmpeg")
    subprocess.run([ff, "-y", "-v", "error", "-framerate", str(fps), "-i", f"{tmp}/%08d.png", "-i", a.audio,
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17", "-c:a", "aac", "-shortest", a.out], check=True)
    print("wrote", a.out, len(out), "frames")


if __name__ == "__main__":
    main()
