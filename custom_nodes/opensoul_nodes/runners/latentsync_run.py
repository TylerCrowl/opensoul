#!/usr/bin/env python3
"""LatentSync runner (official ByteDance/LatentSync-1.6 weights, stage2_512 config).
Runs inside the LatentSync venv. If no system ffmpeg is on PATH, uses imageio-ffmpeg's binary.
Inference goes through latentsync_infer.py: InsightFace is blocked (buffalo_l weights are non-commercial) and
LatentSync's face detector is replaced by OpenSoul's MediaPipe detector (ls_face_detector.py).

--face-box x,y,w,h   speaker's face on the first frame (pixels). Needed when the shot has more than one face.
Writes <out>.lipsync.json next to the output (also on failure): face_found_ratio, held_frames, frames,
detector_counts {mediapipe, anime_fallback, held, none}, face_px_median, face_px_min (face height in output
pixels), multi_face_frames, backend, steps, guidance, seed, status, error. ``frames`` is the number of input frames
the detector saw. Whenever this run wrote the output mp4, the sidecar also has out_frames (frames decoded from the
final file) and out_sha256 (sha256 hex of the final file). The sidecar is written last, after the mux and any mouth
post-processing, so out_sha256 always describes the file exactly as it is left on disk.

Frame rate and length (default --fps-mode source): the output has the source take's frame rate and exactly its
frame count. Audio shorter than the take is padded with silence to the take's length; audio longer than the take
by more than one frame is refused (exit 5, "length_mismatch"; LatentSync would loop the video). The final file
carries the original audio at its own sample rate (LatentSync's own mux is 16 kHz). After writing, the output is
decoded and checked: fps or frame count different from the source = exit 6 ("fps_mismatch" /
"frame_count_mismatch"), mp4 kept for inspection. --fps-mode 25 = upstream behaviour (comparisons only).
--smooth S: landmark smoothing sigma in frames (default 1.0, 0 = off). --mouth-blend F / --mouth-sharpen A:
optional mouth post-processing (ls_mouth_post.py): mix fraction F of the raw mouth back in / unsharp mask amount A.

Exit codes: 0 ok, 3 ambiguous_face, 4 no_face (a frame with no face and nothing to hold, or a face on < 50 %
of frames; the mp4 is kept in that case), 5 length_mismatch, 6 fps_mismatch / frame_count_mismatch
(stderr line "OPENSOUL_LIPSYNC_ERROR <code>: ..."), other = failure."""
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile

EXIT_LENGTH = 5
EXIT_CONFORM = 6
FPS_TOL = 0.01
MIN_FOUND = 0.5  # interface: no_face when a face was found on < 50 % of frames (after hold)
HERE = os.path.dirname(os.path.abspath(__file__))
SIDECAR_KEYS = ("face_found_ratio", "held_frames", "frames", "detector_counts", "face_px_median", "face_px_min",
                "multi_face_frames", "backend", "steps", "guidance", "seed")


def sidecar_path(out: str) -> str:
    return out + ".lipsync.json"  # take.mp4 -> take.mp4.lipsync.json (what opensoul/lipsync.read_sidecar reads)


def file_sha256(path: str) -> str:
    """sha256 hex digest of a file's bytes."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def describe_output(path: str, video_info) -> dict:
    """out_frames (decoded frame count), out_fps and out_sha256 of the finished output file. Call it only after the
    last write to ``path``."""
    fps, n = video_info(path)
    return {"out_fps": round(fps, 4), "out_frames": n, "out_sha256": file_sha256(path)}


def write_sidecar(out: str, d: dict) -> None:
    """Write <out>.lipsync.json atomically (temp file + rename), so a reader never sees a half-written sidecar."""
    p = sidecar_path(out)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, p)


def build_sidecar(stats: dict, steps, guidance, seed, rc: int, face_box=None) -> dict:
    err = stats.get("error") or ({3: "ambiguous_face", 4: "no_face", 5: "length_mismatch"}.get(rc) if rc else None) or (f"exit_{rc}" if rc else None)
    d = {"face_found_ratio": stats.get("face_found_ratio"), "held_frames": stats.get("held_frames", 0),
         "frames": stats.get("frames", 0),
         "detector_counts": stats.get("detector_counts", {"mediapipe": 0, "anime_fallback": 0, "held": 0, "none": 0}),
         "face_px_median": stats.get("face_px_median"), "face_px_min": stats.get("face_px_min"),
         "multi_face_frames": stats.get("multi_face_frames", 0), "backend": "latentsync",
         "steps": int(steps), "guidance": float(guidance), "seed": int(seed),
         "status": "ok" if rc == 0 else "error", "error": err, "face_box": face_box,
         "detector": "mediapipe+anime-face-detector" if stats.get("style", "auto") != "real" else "mediapipe"}
    for k in ("duplicate_detections_dropped", "fps_mode", "source_fps", "source_frames", "out_fps", "out_frames", "out_frames_error", "out_sha256", "chunks_raw", "audio_pad_s",
              "smooth_sigma", "mouth_blend", "mouth_sharpen", "mouth_post"):
        if k in stats:
            d[k] = stats[k]
    return d


def plan_audio(audio_s: float, fps: float, n_frames: int) -> float:
    """Seconds of silence to append so the audio covers the take exactly. Raises ValueError if the audio is longer
    than the take by more than one frame."""
    video_s = n_frames / fps
    if audio_s > video_s + 1.0 / fps:
        raise ValueError(f"audio is {audio_s:.3f} s but the take is {video_s:.3f} s ({n_frames} frames at {fps:g} fps)")
    return max(0.0, video_s - audio_s)


def check_conform(src_fps: float, src_n: int, out_fps: float, out_n: int) -> str | None:
    """None if the output matches the source rate and frame count, else the error code."""
    if abs(out_fps - src_fps) > FPS_TOL:
        return "fps_mismatch"
    if out_n != src_n:
        return "frame_count_mismatch"
    return None


def _read_audio(path: str):
    """(float32 samples (N, C), sample rate). soundfile when installed (the LatentSync venv), else PCM WAV."""
    import numpy as np

    try:
        import soundfile as sf
    except ImportError:
        import wave

        with wave.open(path) as w:
            sw, ch, sr, n = w.getsampwidth(), w.getnchannels(), w.getframerate(), w.getnframes()
            raw = np.frombuffer(w.readframes(n), {1: np.uint8, 2: np.int16, 4: np.int32}[sw])
        a = raw.astype(np.float32).reshape(-1, ch)
        a = (a - 128) / 128 if sw == 1 else a / float(2 ** (8 * sw - 1))
        return a, sr
    a, sr = sf.read(path, dtype="float32", always_2d=True)
    return a, sr


def audio_seconds(path: str) -> float:
    a, sr = _read_audio(path)
    return len(a) / float(sr)


def pad_audio(src: str, dst: str, pad_s: float, n_frames: int, fps: float) -> int:
    """Write src + silence to dst (16-bit WAV, same rate/channels), exactly the take's duration. Returns the rate."""
    import wave

    import numpy as np

    a, sr = _read_audio(src)
    n = int(round(n_frames / fps * sr))
    a = np.concatenate([a, np.zeros((max(0, n - len(a)), a.shape[1]), np.float32)])[:n]
    with wave.open(dst, "wb") as w:
        w.setnchannels(a.shape[1]); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(a, -1, 1) * 32767).round().astype("<i2").tobytes())
    return sr


def read_rgb(path: str) -> list:
    import cv2

    cap, fr = cv2.VideoCapture(path), []
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        fr.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    cap.release()
    return fr


def write_rgb(frames: list, fps: float, path: str) -> None:
    h, w = frames[0].shape[:2]
    p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                          "-r", f"{fps:.6g}", "-i", "-", "-c:v", "libx264", "-crf", "15", "-pix_fmt", "yuv420p", path],
                         stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(f.tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg failed writing the post-processed video")


def fail(code: str, msg: str) -> None:
    print(f"OPENSOUL_LIPSYNC_ERROR {code}: {msg}", file=sys.stderr, flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    for k in ("latentsync-dir", "video", "audio", "out"):
        ap.add_argument("--" + k, required=True)
    ap.add_argument("--steps", default="20"); ap.add_argument("--guidance", default="1.5"); ap.add_argument("--seed", default="1247")
    ap.add_argument("--face-box", default=None, help="x,y,w,h of the speaking face on the first frame (pixels)")
    ap.add_argument("--fps-mode", choices=("source", "25"), default="source")
    ap.add_argument("--smooth", type=float, default=1.0, help="landmark smoothing sigma in frames (0 = off)")
    ap.add_argument("--mouth-blend", type=float, default=0.0, help="fraction of the raw mouth mixed back in (0-1)")
    ap.add_argument("--mouth-sharpen", type=float, default=0.0, help="unsharp-mask amount inside the mouth mask")
    ap.add_argument("--sharpen-sigma", type=float, default=1.2)
    a = ap.parse_args(argv)
    sys.path.insert(0, HERE)
    from latentsync_infer import video_info
    env = dict(os.environ)
    box = None
    if a.face_box:
        x, y, w, h = (float(v) for v in a.face_box.split(","))
        if w <= 0 or h <= 0:
            ap.error("--face-box needs a positive width and height")
        box = [x, y, w, h]
        env["OPENSOUL_LS_FACE_BOX"] = a.face_box
    else:
        env.pop("OPENSOUL_LS_FACE_BOX", None)
    if not shutil.which("ffmpeg"):
        import imageio_ffmpeg
        bindir = tempfile.mkdtemp(prefix="opensoul_ffmpeg_")
        os.symlink(imageio_ffmpeg.get_ffmpeg_exe(), os.path.join(bindir, "ffmpeg"))
        env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
        os.environ["PATH"] = env["PATH"]  # the post-processing writer and the mux use it too
    fd, stats_path = tempfile.mkstemp(prefix="ls_stats_", suffix=".json"); os.close(fd)
    env["OPENSOUL_LS_STATS"] = stats_path
    env["OPENSOUL_LS_FPS"] = a.fps_mode
    env["OPENSOUL_LS_SMOOTH"] = str(a.smooth)
    work = tempfile.mkdtemp(prefix="opensoul_ls_", dir=os.path.dirname(os.path.abspath(a.out)) or None)
    pre = {"fps_mode": a.fps_mode, "smooth_sigma": a.smooth, "mouth_blend": a.mouth_blend, "mouth_sharpen": a.mouth_sharpen}
    audio_in = a.audio
    if a.fps_mode == "source":
        src_fps, src_n = video_info(a.video)
        pre.update(source_fps=round(src_fps, 4), source_frames=src_n)
        try:
            pad = plan_audio(audio_seconds(a.audio), src_fps, src_n)
        except ValueError as e:
            fail("length_mismatch", str(e))
            write_sidecar(a.out, build_sidecar({**pre, "error": "length_mismatch"}, a.steps, a.guidance, a.seed, EXIT_LENGTH, box))
            return EXIT_LENGTH
        audio_in = os.path.join(work, "audio_fit.wav")
        pad_audio(a.audio, audio_in, pad, src_n, src_fps)
        pre["audio_pad_s"] = round(pad, 4)
    ls_out = os.path.join(work, "ls.mp4") if a.fps_mode == "source" else a.out
    cmd = [sys.executable, os.path.join(HERE, "latentsync_infer.py"), "--unet_config_path", "configs/unet/stage2_512.yaml",
           "--inference_ckpt_path", "checkpoints/latentsync_unet.pt", "--inference_steps", a.steps,
           "--guidance_scale", a.guidance, "--seed", a.seed, "--enable_deepcache",
           "--video_path", a.video, "--audio_path", audio_in, "--video_out_path", ls_out,
           "--temp_dir", os.path.join(os.path.dirname(os.path.abspath(a.out)), "lstmp")]
    rc = subprocess.call(cmd, cwd=a.latentsync_dir, env=env)
    try:
        with open(stats_path) as f:
            stats = json.load(f)
    except (OSError, ValueError):
        stats = {}
    finally:
        try:
            os.remove(stats_path)
        except OSError:
            pass
    stats.update({k: v for k, v in pre.items() if k not in stats or k in ("source_fps", "source_frames")})
    wrote_out = rc == 0 and a.fps_mode == "25"  # 25 mode: LatentSync wrote --out itself
    if rc == 0 and a.fps_mode == "source":
        try:
            vid = ls_out
            if a.mouth_blend > 0 or a.mouth_sharpen > 0:
                import ls_mouth_post as MP

                frames, mstats = MP.process_frames(read_rgb(ls_out), read_rgb(a.video), MP.LipFinder(),
                                                   a.mouth_blend, a.mouth_sharpen, a.sharpen_sigma)
                vid = os.path.join(work, "post.mp4")
                write_rgb(frames, src_fps, vid)
                stats["mouth_post"] = mstats
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", vid, "-i", audio_in, "-map", "0:v:0", "-map", "1:a:0",
                   "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", f"{src_n / src_fps:.6f}", a.out]
            if subprocess.call(cmd, env=env) != 0:
                raise RuntimeError("ffmpeg mux failed")
            wrote_out = True
            stats.update(describe_output(a.out, video_info))
            bad = check_conform(src_fps, src_n, stats["out_fps"], stats["out_frames"])
            if bad:
                fail(bad, f"output {stats['out_frames']} frames at {stats['out_fps']:g} fps, source {src_n} frames at {src_fps:g} fps")
                stats["error"] = bad
                rc = EXIT_CONFORM
        except Exception as e:  # noqa: BLE001 - recorded in the sidecar, then a non-zero exit
            fail("postprocess_failed", f"{type(e).__name__}: {e}")
            stats["error"] = f"postprocess_failed: {e}"
            rc = 1
    shutil.rmtree(work, ignore_errors=True)
    if wrote_out and "out_sha256" not in stats and os.path.isfile(a.out):
        # 25 mode: upstream can loop the video to cover the audio, so the output may have more frames than the
        # detector saw (``frames``); out_frames is counted from the file itself. Record only: the exit code is unchanged.
        try:
            stats.update(describe_output(a.out, video_info))
        except Exception as e:  # noqa: BLE001
            stats.update(out_frames=None, out_sha256=file_sha256(a.out), out_frames_error=f"{type(e).__name__}: {e}")
    ratio = stats.get("face_found_ratio")
    if rc == 0 and ratio is not None and ratio < MIN_FOUND:
        stats["error"] = "no_face"
        print(f"OPENSOUL_LIPSYNC_ERROR no_face: face found on {ratio:.0%} of frames (< {MIN_FOUND:.0%})",
              file=sys.stderr, flush=True)
        rc = 4
    write_sidecar(a.out, build_sidecar(stats, a.steps, a.guidance, a.seed, rc, box))  # last write of this run
    return rc


if __name__ == "__main__":
    sys.exit(main())
