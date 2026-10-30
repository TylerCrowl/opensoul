# OpenSoul architecture

```
┌─────────────┐     Comfy SDK (comfy-sdk)      ┌──────────────────┐
│ Gradio UI   │ ─────────────────────────────► │ comfy-api-proxy  │
│ app/ui.py   │   COMFY_BASE_URL (:8189)       │     :8189        │
└──────┬──────┘                                └────────┬─────────┘
       │                                                │
       │ CPU: consistency, packs                        ▼
       │                                       ┌──────────────────┐
       └────────────────────────────────────── │ ComfyUI :8188    │
                                               │ open-weights     │
                                               │ Qwen / LTX / …   │
                                               └──────────────────┘
```

## Stages

1. **Character Builder** — one upload + consent → **Character Sheet** (`opensoul/character_sheet.py`, `workflows/07`): six views via Qwen-Image-Edit-2511, each through the identity gate node with one retry, Pillow 3×2 grid → `CharacterPack` / Soul Pack on disk (`pack.json`, `refs/` incl. `sheet_*.png`, `character_sheet.jpg`, prompt lock, seed, optional LoRA path). API: `POST /api/sheet`, poll `GET /api/sheet/{id}`.
2. **Consistent Stills** — scene prompt + pack → N vertical stills (Qwen edit / conditioned gen) → **consistency gate** (`opensoul.consistency`) rejects off-model frames.
3. **Talking Vertical Video** — script → Kokoro TTS → LTX-2.5 I2V (9:16) → MuseTalk lip-sync → captions → MP4.

## Repo layout

| Path | Role |
|------|------|
| `app/ui.py` | UI entrypoint (FastAPI app in `app/server.py`; Gradio was replaced) |
| `opensoul/` | Pack, consistency, Comfy client, pipeline |
| `workflows/` | ComfyUI API-format JSON (stubs → replace with Spark exports) |
| `scripts/setup_spark.sh` | DGX Spark one-command bootstrap |
| `assets/demo_samples/` | Bundled demo characters Lumi (**all rights reserved**) and Pixel (Apache-2.0) |
| `assets/example_character/` | Neutral **Pixel** (Apache-2.0) |

## Dry-run mode

`OPENSOUL_DRY_RUN=1` (default in UI) exercises pack + consistency + UI without ComfyUI.  
Unset on Spark after `comfy-api-proxy` is up.

## Contest mapping

| Requirement | How we hit it |
|-------------|----------------|
| Comfy Developer Platform | Official **Comfy SDK** + self-hosted API v2 proxy |
| Open-source license | Apache-2.0 (`LICENSE`) |
| Workflow files | `workflows/*.json` |
| Local setup | README + `scripts/setup_spark.sh` |
| Usable interface | Gradio |
| Example outputs | Pixel and Lumi dry-run; Lumi story takes from the GPU path |
| Open Weights Only | Qwen + LTX/Wan + Kokoro + MuseTalk; no partner nodes |
| LTX bonus (optional) | LTX-2.5 as core I2V model |
