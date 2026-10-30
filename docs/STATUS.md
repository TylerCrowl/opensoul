# What works today, what is experimental, what is planned

An honest snapshot of the app. "Verified" means it ran on the reference machine, one NVIDIA DGX Spark (GB10, 128 GB
unified memory), with numbers in [HARDWARE_MEMORY.md](HARDWARE_MEMORY.md). Everything else is marked **experimental**,
**estimate** or **unverified**. When this page and the code disagree, the code and its tests win; please open an issue.

## Verified on the DGX Spark

| Area | What runs | Evidence |
|---|---|---|
| App | FastAPI app, six tabs: Characters → Stages → Shots → Render → Review → Export; preview mode on CPU (`OPENSOUL_DRY_RUN=1`) | CPU test suite (`pytest -q`) |
| Characters (Soul Pack) | Six-view sheet with Qwen-Image-Edit-2511 bf16, Qwen3-VL-8B self-check, identity gate, Z-Image-Turbo text-only masters | Qwen-Image-Edit still: 218 s, 28.8 GB (clean run, Oct 17 2026) |
| Video | LTX-2.5 distilled bf16, image-to-video and audio-to-video, 13 prompt-driven camera moves | a2v take: 175 s, 70.7 GB, 1024×1792, 97 frames |
| Lip-sync | `ltx_av` (LTX-2.5 a2v, camera-locked) is the default; LatentSync 1.6 is an opt-in mouth refine | LatentSync: ~197 s, 21.6 GB |
| Voice | VoxCPM2 is the default for new stories; Orpheus is the fallback and rollback; Chatterbox and Kokoro are options | Voice engine tests; VoxCPM2 runs in its own venv |
| Export | 16:9 or 9:16 per story; captions carry the AI-generated label | Export tests |
| Agents | MCP server with six job tools over the app routes (stdio + loopback HTTP), see [MCP.md](MCP.md) | `tests/test_mcp_server.py` (mocked backend) |

Videos made with OpenSoul are AI-generated; shared captions, the credits card and the README say so.

## Experimental (in the repo, not validated end to end)

- **Music videos** (was the Music tab). The CPU side (beats, lyrics timing, shot list) is done and tested. The GPU song step
  (ACE-Step 1.5 XL Turbo, `workflows/08m`) has **never been run from the app** (`gpu_validated: false` in
  `presets/music_models.json`; Music videos says "Not tested in OpenSoul yet."). The demo music video was made with
  standalone scripts that call ComfyUI directly, not with Music videos.
- **Recast / motion transfer.** Union Control IC-LoRA notes only ([GENJUTSU_EVAL.md](GENJUTSU_EVAL.md)).
- **Setup tools** (model manifest, install plan, slot swap, MCP setup tools; [SETUP.md](SETUP.md)). Planning and the
  checks are tested on CPU with mocks. Installing with approval has **not** been run on any machine yet.
- **Recommendation-only tiers** for NVIDIA 8–16 GB cards, Apple Silicon and CPU-only computers in the picker: all
  estimates or author-reported figures; the app has no Mac backend.
- **Music video, UGC ad and product-shot templates** are data stubs behind feature flags that are off by default;
  reframe is documented only ([TEMPLATES.md](TEMPLATES.md)).

## Hardware and models

Only the DGX Spark row is measured. Every other row is an **estimate** or a figure **reported by the tool's authors**,
and has **not been tested by us**. The app's picker shows the same labels.

| Machine | Pictures / edit | Video | Lip-sync | Music | Voice | Status |
|---|---|---|---|---|---|---|
| DGX Spark, 128 GB unified | Qwen-Image-Edit-2511 bf16; Z-Image-Turbo | LTX-2.5 bf16 a2v, camera-locked | `ltx_av` default; LatentSync 1.6 opt-in | ACE-Step 1.5 XL Turbo (not run from the app) | VoxCPM2 default; Orpheus fallback | **Verified** (pictures, video, lip-sync measured) |
| 2 × DGX Spark | machine B | machine A | machine A | machine B | machine B | **Planned**: the app talks to one ComfyUI address today |
| NVIDIA 32 GB (RTX 5090) | Qwen-Image-Edit-2511 fp8 mixed, ~24 GB | LTX-2.5 int8 `--lowvram`, ~30 GB | `ltx_av`; LatentSync ~22 GB | ACE-Step 1.5 XL Turbo | Chatterbox | Estimate, in the app's picker |
| NVIDIA 24 GB (3090, 4090) | Qwen-Image-Edit-2511 fp8 mixed, ~23 GB (tight) | LTX-2.5 int8 `--lowvram`, ~24 GB | `ltx_av`; LatentSync ~22 GB (tight) | ACE-Step 1.5, ~24 GB (at the limit) | Kokoro-82M | Estimate, in the app's picker |
| NVIDIA 16 GB | Z-Image-Turbo bf16; Qwen-Image-Edit-2511 GGUF Q4–Q5 | LTX-2.5 distilled GGUF Q4_K_M + offload | LTX-2.5 a2v GGUF Q4 | ACE-Step 1.5 2B | VoxCPM2 | Estimate, **recommendation only**, unverified |
| NVIDIA 12 GB | Z-Image-Turbo fp8 / GGUF; Qwen-Image-Edit GGUF Q4 + offload | Wan2.2 TI2V-5B GGUF; LTX-2.5 GGUF Q3–Q4 + offload | LTX-2.5 a2v GGUF (experimental) | ACE-Step 1.5 2B | Kokoro or Chatterbox | Estimate, **recommendation only**, unverified |
| NVIDIA 8 GB | FLUX.2 klein 4B; Qwen-Image-Edit GGUF Q2–Q3 + offload (slow) | Wan2.2 TI2V-5B GGUF Q4, 480p drafts | no good local option | ACE-Step 1.5 2B with offload | Kokoro-82M | Estimate, **recommendation only**, unverified |
| Apple Silicon 16–128 GB | mflux builds of Z-Image-Turbo / FLUX.2 klein / Qwen-Image-Edit | LTX MLX ports (q4 / q8) | LTX a2v via MLX | ACE-Step 1.5 on MPS | Kokoro (MLX); VoxCPM2 on MPS unverified | **Not supported by the app yet**; recommendation only, reported by tool authors, unverified |
| CPU only | none practical | point a slot at a remote ComfyUI | remote | ACE-Step 1.5 on CPU (slow) | Kokoro-82M | Write, plan and voice locally; render elsewhere |

Mac notes (unverified by us):

- ComfyUI on Apple's MPS backend has an open bug where bf16 LTX-2.x runs can come out all black
  ([ComfyUI issue 15804](https://github.com/Comfy-Org/ComfyUI/issues/15804)). Mac video should go through the MLX
  ports instead (`dgrauet/ltx-2.5-mlx-q4` / `-q8`, the `comfyui-ltx2-mlx` nodes for LTX-2.3).
- Qwen-Image-Edit is heavy on a Mac (a q8 build is reported at 96 GB+); smaller Macs should edit with FLUX.2 klein 4B.
- LatentSync, the Wan 14B models and other CUDA-only nodes are not offered on a Mac.
- No Mac speed has been measured. The OpenSoul runners are Linux + NVIDIA only today.

Licences follow the picker's three allowed classes (open; LTX-2.x with the AI-generated label; open weights with use
restrictions). Non-commercial weights (FLUX.2-dev, InsightFace `buffalo_l`, Demucs) are never offered. The full model
list per slot, with licence, memory, disk size and source, is [presets/model_manifest.yaml](../presets/model_manifest.yaml)
(`GET /api/hardware/slots`), and in the app in the Models tab, before Characters (dry-run plans only; you approve from a
terminal, see [SETUP.md](SETUP.md#models-screen-in-the-app)).
