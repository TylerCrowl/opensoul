# Memory and speed on the tested machine

Measured, not estimated. Source: the render-runner logs on the test machine (an NVIDIA DGX Spark: GB10, 121.7 GiB usable unified memory, driver 580.173.02), Oct 16-17 2026. Every runner job logs its wall-clock time and the **lowest `MemAvailable` seen while the job ran** (polled from `/proc/meminfo`).

Important caveat: on unified memory there is no separate VRAM counter (`nvidia-smi` reports memory as N/A), so these numbers are **whole-system**. They include ComfyUI, the OS, the app, and whatever else was resident. They are an upper bound for a stage, not the model's own footprint.

| Stage (ComfyUI, via the runner) | Settings | Jobs | Wall time median (min-max) | Lowest MemAvailable median (min-max) | Implied whole-system use at peak |
|---|---|---|---|---|---|
| LTX-2.5 a2v / i2v video take (`04_i2v_ltx_api.json`, `04b_a2v_ltx_api.json`) | bf16, 1024×1792, 97 frames, 2-stage with upsampler | 188 | 225 s (135-866 s) | 45.0 GB (22.5-75.3 GB) | ~77 GB median |
| Consistent still / sheet view (Qwen-Image-Edit-2511 bf16) | 1 image | 17 | 394 s (204-508 s) | 86.4 GB (44.9-88.3 GB) | ~35 GB median |

How to read it:

- The low tail (22.5 GB available) comes from runs where a LatentSync or Qwen-Image-Edit job overlapped an LTX job. The runner now waits for `MemAvailable >= 30 GB` before each take and calls ComfyUI `/free` around still jobs, so LTX and Qwen-Image-Edit are never resident together.
- Long tails in wall time are first-load runs (cold weights from disk) or contention with an overlapping job.
- 128 GB unified memory runs the full bf16 stack one stage at a time with headroom. It does **not** have room for LTX bf16 plus Qwen-Image-Edit bf16 plus a large local LLM all at once.

## Per-stage peaks in isolation (clean run, Oct 17 2026)

One clean run on the same Spark with nothing else rendering: each stage ran alone, ComfyUI `/free` was called between stages, and a 1 Hz sampler logged `MemAvailable` plus the GPU process memory reported by `nvidia-smi --query-compute-apps` (that per-process counter does work on unified memory). Raw samples: [evidence/h3_mem.csv](evidence/h3_mem.csv) (columns: epoch, MemAvailable GB, GPU process MiB, phase). Idle baseline: 116.9 GB available (median of 106 idle samples).

| Stage | Settings | Wall time | Peak drop in MemAvailable vs idle | Peak GPU process memory |
|---|---|---|---|---|
| Qwen-Image-Edit-2511 still (warm ComfyUI) | bf16, 1 image | 218 s | 28.8 GB | 28.7 GiB |
| LTX-2.5 a2v take | bf16, 1024×1792, 97 frames, 2-stage with upsampler | 175 s | 70.7 GB | 68.0 GiB |
| LatentSync lip-sync | 1.6 (checkpoint sha256 matches ByteDance/LatentSync-1.6; "1.5" here earlier was the guidance value), own env, same 97-frame take | ~197 s | 21.6 GB | 17.0 GiB |

What this means: LTX-2.5 bf16 is the stage that sets the hardware bar (about 68-71 GB on its own). Qwen-Image-Edit bf16 and LatentSync each fit under 30 GB, so either could run on a 32 GB card at bf16; LTX bf16 cannot fit a 24-32 GB card without fp8/low-VRAM offload (still untested, see below). One run per stage, so treat these as single measurements, not averages.

Not measured yet (honest gaps):

- **24 GB discrete GPUs (RTX 3090/4090/5090) are untested.** The README's fp8/int8 + `--lowvram` advice is a plan, not a result.
- Kokoro, Chatterbox and the ArcFace gate are small next to LTX and run in their own envs; their own peaks are not broken out here.

To reproduce on your machine: run any job with `scripts/spark_render_jobs.py`-style polling, or simply watch `free -g` (unified memory) or `nvidia-smi --query-gpu=memory.used --format=csv -l 1` (discrete GPU) during a render.

## Hardware picker

Settings → **Models for this computer** (also offered once on first launch) turns the numbers above into one model per stage. Config: [presets/hardware_profiles.yaml](../presets/hardware_profiles.yaml); code: `opensoul/hardware.py`; API: `GET /api/hardware/detect`, `GET /api/hardware/recommend?tier=<id>`, `GET /api/hardware/tiers`, `GET|POST /api/hardware/settings`.

| Tier | Status | Pictures | Video + lip-sync | Voice | Music |
|---|---|---|---|---|---|
| 1 × DGX Spark | **tested (measured on Spark)** for pictures, video and lip-sync; voice and music are estimates | Qwen-Image-Edit-2511 bf16 · 28.8 GB measured | LTX-2.5 bf16 a2v, camera-locked · 70.7 GB measured; Stage 2 LatentSync 1.6 · 17–22 GB measured | Chatterbox (recommended) · ~6 GB est. | ACE-Step 1.5 XL Turbo · ~24 GB est. |
| 2 × DGX Spark | **planned**: the app talks to one ComfyUI address today | on Spark B · ~29 GB est. | on Spark A · ~71 GB est.; Stage 2 ~22 GB est. | on Spark B | on Spark B |
| 32 GB card (RTX 5090) | untested (estimate) | Qwen-Image-Edit-2511 fp8 mixed · ~24 GB est. | LTX-2.5 int8 a2v with `--lowvram` · ~30 GB est.; Stage 2 ~22 GB est. | Chatterbox (recommended) | ACE-Step · ~24 GB est. |
| 24 GB card | untested (estimate) | Qwen-Image-Edit-2511 fp8 mixed · ~23 GB est. (tight) | LTX-2.5 int8 a2v with `--lowvram` · ~24 GB est., may need a smaller size or fewer frames; Stage 2 ~22 GB est. (tight) | Kokoro-82M · ~1 GB est. | ACE-Step · ~24 GB est. (at the limit) |
| Anything smaller, or no NVIDIA GPU | no tested or estimated stack; a **recommendation-only** tier from the model manifest instead (below) | – | – | – | – |

- Only the Spark numbers in the tables above are measurements. Everything marked "est." is worked out from the model files' sizes (read from the Hugging Face Hub, cited as `hf:<repo>@<revision>` in the yaml) and has not been run on that hardware. The yaml keeps the two apart (`measured_gb` vs `est_gb` with `source: estimate`), and the tests fail if an untested tier carries a measured number.
- Licences, in three allowed classes: **open** (Apache-2.0, MIT, BSD, CC0, CC-BY-4.0 with credit); **LTX-2.x** (gated download, free under $10M yearly revenue, AI-generated label); and **open weights, use-restricted** (OpenRAIL++-M and the Llama 3.2 Community License: commercial use allowed; some uses prohibited), shown with an amber badge. LatentSync 1.6 (OpenRAIL++-M) is the lip-sync card's Stage 2 and Orpheus 3B (built on Llama 3.2) is a voice option in that class. Demucs (research-only) and InsightFace (non-commercial) stay blocked and are listed under "Models we don't offer, and why".
- Lip-sync, as the app runs it: LTX-2.5 a2v with the camera locked (the voice goes into the video model, `workflows/04b_a2v_ltx_api.json`), then LatentSync 1.6 as Stage 2 when it is installed and the face is clear (recipe L1c in `opensoul/lipsync.py`). Stage 2's 17–22 GB is the clean-run measurement above (17.0 GiB GPU process, 21.6 GB drop).
- Voice options (under the Voice card): **VoxCPM2** (Apache-2.0, `hf:openbmb/VoxCPM2@32279effe8c19989596f05d353d1447f51d9e915`, 4.6 GB model + 0.38 GB audio VAE) is the default for new stories (`presets/voice_engine.json` `tts_default_new`): each character speaks in their own voice clip (consent required), and a character without a usable clip speaks with Orpheus, with a note. **Chatterbox** (MIT) is the picker's recommendation. **Orpheus 3B** stays the app's `default_backend` (`presets/models.yaml`): the Speak tab, older stories and that fallback use it, so existing projects and packs (Lumi tara, Mio leah, Ren zac, Pixel jess) render unchanged (`tests/test_voice_backcompat.py`). Rollback: `OPENSOUL_TTS_DEFAULT=orpheus` (new stories) or `OPENSOUL_TTS=orpheus` (every line). **Kokoro-82M** (Apache-2.0).
- 2 × DGX Spark is **planned**, not just untested: the app talks to one ComfyUI address (`COMFY_BASE_URL`) today, so it can't send stages to a second computer yet.
- Detection is local and read-only: `nvidia-smi` (5 s timeout), else `torch.cuda` in a child process (10 s timeout), plus `/proc/meminfo`. A GB10 / Grace GPU (memory reported as N/A) counts as Spark-class unified memory. The number of computers is never discovered over the network: it is `OPENSOUL_MACHINES`, else the Settings value, else 1.
- Preview mode (`OPENSOUL_DRY_RUN=1`) can simulate a computer: `/?settings=1&simulate=spark|spark_x2|rtx5090|rtx24|cpu`.

### Model manifest (one slot per step)

[presets/model_manifest.yaml](../presets/model_manifest.yaml) lists one swappable slot per pipeline step (image, edit,
video, lip-sync, music, voice, upscale) with the app's default, every option, and for each option its licence and
licence class, commercial use (yes / conditional / no), memory, download size and source. Models the app runs read
their facts from `presets/hardware_profiles.yaml` and `presets/models.yaml`, so nothing is copied. Candidates the app
does not run yet (GGUF, MLX, FLUX.2 klein 4B, Wan2.2 TI2V-5B, SeedVR2-3B and others) carry their own facts, read from
the Hugging Face Hub on Oct 23 2026, and their memory is always an estimate or an author-reported figure. Code:
`opensoul/model_manifest.py`; API: `GET /api/hardware/slots?commercial=any|allowed|open_only`.

### Recommendation-only tiers (8-16 GB NVIDIA, Apple Silicon, CPU only)

When the picker lands on its fallback, the page shows a recommendation-only tier from
`presets/model_manifest.yaml` (`advisory_tiers`) instead of a bare "no recommendation": NVIDIA 16 / 12 / 8 GB,
Apple Silicon 128 / 64 / 32 / 16 GB, and CPU only. One card per slot, each an estimate or an author-reported figure,
never a measurement, and nothing the app runs or defaults to changes. Macs are detected locally with `sysctl` (chip
and unified memory, 5 s timeout) and get the Mac notes: the ComfyUI MPS bf16 black-video bug (issue 15804), the MLX
ports, Qwen-Image-Edit's size on a Mac, and CUDA-only nodes left out. The app itself has no Mac backend yet.
Licence filter: `?commercial=allowed|open_only` on `/api/hardware/recommend` marks (never silently drops) cards whose
licence it hides. Preview mode can simulate these computers too: `?simulate=rtx4080|rtx3060|rtx4060|mac16|mac32|mac64|mac128`.

