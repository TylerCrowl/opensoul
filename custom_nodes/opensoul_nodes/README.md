# OpenSoul Nodes for ComfyUI

Nodes that turn a ComfyUI graph into a talking, on-model character shot, using open weights only:

| Node | What it does | Model and license |
|---|---|---|
| **OpenSoul Kokoro TTS** | Text to speech (`AUDIO`), 11 stock voices, speed control | Kokoro-82M, Apache-2.0 |
| **OpenSoul Chatterbox TTS** | Expressive text to speech with exaggeration / CFG / seed, optional voice reference | Chatterbox, MIT (output carries Resemble's Perth watermark) |
| **OpenSoul VoxCPM2 TTS** | Text to speech from the plain words (tags and `(style)` notes are removed, it would read them aloud); optional voice reference clones a voice you made or may use (48 kHz). Runs in its own venv (`scripts/setup_tts_voxcpm2.sh`), denoiser off | VoxCPM2, Apache-2.0 |
| **OpenSoul Orpheus TTS** | Expressive text to speech (fallback voice engine; new stories use VoxCPM2): 8 built-in voices, inline emotion tags `<laugh>` `<chuckle>` `<sigh>` `<gasp>` `<cough>` `<sniffle>` `<groan>` `<yawn>`, temperature / seed | Orpheus 3B 0.1-ft, Apache-2.0, **Built with Llama** (Llama 3.2 Community License); SNAC decoder MIT |
| **OpenSoul LatentSync Lip-Sync** | Re-syncs a `VIDEO`'s mouth to an `AUDIO` track (optional; the app default is LTX audio+video, workflow 04b) | LatentSync 1.6: code Apache-2.0, weights OpenRAIL++. Face detector: MediaPipe FaceLandmarker (Apache-2.0) + optional anime-face-detector (MIT); InsightFace is blocked |
| **OpenSoul Identity Gate** | Scores every candidate frame against an anchor image and passes only on-model frames | `patch` backend: in-process, Apache-2.0, no weights. Optional `arcface` backend: InsightFace buffalo_l (non-commercial research weights; opt in knowingly) |

## Why the Identity Gate exists

Generated character views drift: a different jaw, a missing cap, a new beard. The gate makes
"is this still the same character?" a node you can wire into any graph. It outputs the frames
that pass, the best score, a `passed` boolean and a JSON report, so a graph (or the OpenSoul app)
can auto re-roll a view instead of leaving the fix to the user. With `fail_on_reject` it stops
the run outright.

Inputs: `anchor` (IMAGE, first frame used), `candidates` (IMAGE batch), `threshold`
(`-1` = backend default: patch 0.70, arcface 0.45), `fail_on_reject`, optional `backend`.
Outputs: `passed_images`, `best_score`, `passed`, `report`. If nothing passes, the single best
frame is returned with `passed = False`.

## Install

```bash
ln -s "$PWD/custom_nodes/opensoul_nodes" "$COMFY_DIR/custom_nodes/"
```

The pack adds **no dependencies to the ComfyUI env**. The Identity Gate's default backend runs
in-process with numpy and Pillow (already in ComfyUI). TTS, lip-sync and the optional ArcFace
backend each run in their own Python venv through the small scripts in `runners/`, so their
pinned torch / diffusers versions never clash with ComfyUI's. The top-level repo's
`scripts/download_models.sh` fetches every model from Hugging Face.

## Configuration (environment variables)

| Variable | Default |
|---|---|
| `OPENSOUL_HOME` | `~/OpenSoul` |
| `OPENSOUL_KOKORO_PY` | `$OPENSOUL_HOME/tts-env/bin/python` |
| `OPENSOUL_KOKORO_DIR` | `$OPENSOUL_HOME/models/kokoro` |
| `OPENSOUL_CHATTERBOX_PY` | `$OPENSOUL_HOME/chatterbox-env/bin/python` |
| `OPENSOUL_ORPHEUS_PY` | `$OPENSOUL_HOME/tts-envs/orpheus/bin/python` (made by `scripts/setup_tts_orpheus.sh`) |
| `OPENSOUL_ORPHEUS_GGUF` | `$OPENSOUL_HOME/models/orpheus/Orpheus-3b-FT-Q4_K_M.gguf` |
| `OPENSOUL_LATENTSYNC_PY` | `$OPENSOUL_HOME/latentsync-env/bin/python` |
| `OPENSOUL_LATENTSYNC_DIR` | `$OPENSOUL_HOME/LatentSync` |
| `OPENSOUL_IDSIM_PY` | `$OPENSOUL_HOME/latentsync-env/bin/python` (needs `insightface`; only for `backend="arcface"`) |

## Lip-sync runner (`runners/latentsync_run.py`)

- Runs LatentSync through `runners/latentsync_infer.py`, which blocks `import insightface` (upstream's detector
  auto-downloads InsightFace `buffalo_l`, licensed for non-commercial research only) and installs
  `runners/ls_face_detector.py` in its place. LatentSync's own crop / affine / restore code is unchanged.
- Model files: `$OPENSOUL_HOME/models/mediapipe/face_landmarker.task` (`OPENSOUL_MP_FACE_TASK`;
  `./scripts/download_models.sh lipsync` fetches it sha256-pinned). Anime fallback when `anime-face-detector`
  0.1.x (pure PyTorch, `pip install "git+https://github.com/hysts/anime-face-detector@98a9fb4"`) is installed in
  latentsync-env (`OPENSOUL_LS_ANIME=0` turns it off). `OPENSOUL_LS_FACE_STYLE=auto|real|anime`,
  `OPENSOUL_LS_HOLD` (frames to hold the last face, default 12).
- `--face-box x,y,w,h` (first-frame pixels) picks the speaker; the detector then tracks that face. Without it and
  with 2+ faces the runner exits 3 (`ambiguous_face`); no face (or a face on < 50 % of frames) exits 4 (`no_face`).
  stderr carries `OPENSOUL_LIPSYNC_ERROR <code>: ...`.
- Writes `<out>.lipsync.json`: `face_found_ratio`, `held_frames`, `frames`, `detector_counts` {mediapipe,
  anime_fallback, held, none}, `face_px_median`, `face_px_min`, `multi_face_frames`, `backend`, `steps`,
  `guidance`, `seed`, plus `status`, `error`, `face_box`.
- latentsync-env still has `insightface` installed from LatentSync's requirements; it is never imported on this
  path (`pip uninstall insightface` there is safe unless you use the opt-in ArcFace gate from the same env).

## Measured cost (DGX Spark, Oct 2026)

LatentSync is about 197 s and a 17.0 GiB GPU process peak per ~4 s shot (see the repo's
`docs/HARDWARE_MEMORY.md`). The patch Identity Gate runs on CPU in milliseconds per frame.

## License

Apache-2.0 (see `LICENSE`). Model weights keep their own licenses, listed above.
