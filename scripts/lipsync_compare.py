#!/usr/bin/env python3
"""Build lip-sync comparison videos for judging BY EYE (scores are only a pre-filter).

Given N clips with labels, writes two files:
  <out>_side.mp4  - all clips side by side, same height, labelled; audio from --audio-from (default 0)
  <out>_seq.mp4   - each clip in turn with ITS OWN audio, labelled (so each one's sync can be heard)

Usage:
  python scripts/lipsync_compare.py --out out/ab_lumi \
      "LTX a2v=path/a.mp4" "InfiniteTalk=path/b.mp4" "Benchmark (closed, not used)=ref.mp4"
"""
import argparse, os, re, shutil, subprocess, sys, tempfile

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


def font():
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            return f
    return None


def ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        sys.exit("ffmpeg not found (install ffmpeg or imageio-ffmpeg)")


def probe_duration(ff, path):
    # parse "Duration: HH:MM:SS.xx" from ffmpeg -i (works without ffprobe)
    p = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True)
    for line in p.stderr.splitlines():
        line = line.strip()
        if line.startswith("Duration:"):
            h, m, s = line.split(",")[0].split()[1].split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0


def has_audio(ff, path):
    p = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True)
    return "Audio:" in p.stderr


def probe_size(ff, path):
    p = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True)
    for line in p.stderr.splitlines():
        if "Video:" in line:
            m = re.search(r" (\d{2,5})x(\d{2,5})[ ,]", line)
            if m:
                return int(m.group(1)), int(m.group(2))
    return 16, 9


def esc(t):
    return t.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\u2019").replace("%", "\\%")


def label_filter(label, fnt, h, w=None):
    size = h // 24
    if w:  # keep the label inside a narrow (e.g. 9:16) pane
        size = min(size, int(w * 0.92 / (0.72 * max(1, len(label)))))
    size = max(12, size)
    f = f"fontfile='{fnt}':" if fnt else ""
    return (f"drawtext={f}text='{esc(label)}':fontsize={size}:fontcolor=white:"
            f"box=1:boxcolor=black@0.55:boxborderw={size//3}:x=(w-text_w)/2:y=h-text_h-{size}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+", help='"Label=path.mp4"')
    ap.add_argument("--out", required=True, help="output prefix (no extension)")
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--audio-from", type=int, default=0, help="clip index whose audio plays in _side")
    a = ap.parse_args()

    items = []
    for c in a.clips:
        if "=" not in c:
            sys.exit(f"expected Label=path, got {c!r}")
        lab, path = c.split("=", 1)
        if not os.path.exists(path):
            sys.exit(f"missing clip: {path}")
        items.append((lab, path))

    ff, fnt, H = ffmpeg(), font(), a.height - a.height % 2
    durs = [probe_duration(ff, p) for _, p in items]
    longest = max(durs)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    enc = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]

    # side by side: scale each to H, hold last frame to the longest duration
    inputs, parts = [], []
    for i, (lab, p) in enumerate(items):
        inputs += ["-i", p]
        pad = max(0.0, longest - durs[i])
        sw, sh = probe_size(ff, p)
        pw = int(sw * H / sh)
        parts.append(f"[{i}:v]fps={a.fps},scale=-2:{H},setsar=1,"
                     f"tpad=stop_mode=clone:stop_duration={pad:.3f},{label_filter(lab, fnt, H, pw)}[v{i}]")
    stack = "".join(f"[v{i}]" for i in range(len(items)))
    fc = ";".join(parts) + f";{stack}hstack=inputs={len(items)}[v]" if len(items) > 1 else \
        ";".join(parts) + ";[v0]null[v]"
    ai = a.audio_from
    amap = ["-map", f"{ai}:a:0"] if has_audio(ff, items[ai][1]) else []
    side = a.out + "_side.mp4"
    subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", fc,
                    "-map", "[v]", *amap, *enc, "-t", f"{longest:.3f}", side], check=True)

    # sequence: each clip with its own audio, letterboxed to a common 16:9 canvas at H
    W = (H * 16 // 9) // 2 * 2
    with tempfile.TemporaryDirectory() as td:
        segs = []
        for i, (lab, p) in enumerate(items):
            seg = os.path.join(td, f"s{i}.mp4")
            vf = (f"fps={a.fps},scale={W}:{H}:force_original_aspect_ratio=decrease,"
                  f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,{label_filter(lab, fnt, H)}")
            if has_audio(ff, p):
                cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", p, "-vf", vf,
                       "-af", "aresample=48000", "-ac", "2", *enc, seg]
            else:
                cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", p,
                       "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-vf", vf,
                       "-shortest", *enc, seg]
            subprocess.run(cmd, check=True)
            segs.append(seg)
        lst = os.path.join(td, "list.txt")
        with open(lst, "w") as f:
            f.writelines(f"file '{s}'\n" for s in segs)
        seq = a.out + "_seq.mp4"
        subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", lst, "-c", "copy", seq], check=True)
    print(side)
    print(seq)


if __name__ == "__main__":
    main()
