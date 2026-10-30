# Contributing to OpenSoul

We appreciate your help. OpenSoul aims to be usable by anyone, so changes should keep the main path plain-language and simple.

## Dev setup (no GPU needed)

```bash
./scripts/setup_dev.sh
source .venv/bin/activate
OPENSOUL_DRY_RUN=1 pytest -q
OPENSOUL_DRY_RUN=1 opensoul-ui   # http://127.0.0.1:7860
```

ffmpeg must be on `PATH` (Era grade, dry-run renders, export).

## Add a camera move or effect

1. Copy a file in `presets/camera/` or `presets/effects/` and give it a new `id` (the filename matches the id).
2. Write a long, specific `prompt` (lens, speed, path, what stays fixed). Set `lora` to `null` unless an LTX LoRA exists for the move.
3. Keep `defaults` vertical (704×1280). Set `order` for its tile position.
4. Optional: render a looping 9:16 MP4 to `assets/preset_thumbs/<camera|effects>/<id>.mp4`. Until it exists, the UI shows an animated placeholder.
5. Run `pytest`. `tests/test_presets_and_shot_api.py` checks the preset schema.

## Add a lip-sync or video backend

Implement the small interfaces in `opensoul/speak.py` (`LipSyncBackend.sync`) or `opensoul/shot.py` (`VideoBackend.render`), register it in `get_lipsync`, and keep a dry-run path that works with ffmpeg only. GPU imports stay lazy.

## Workflows

ComfyUI graphs in `workflows/` are API-format exports. If you change node ids, update the matching `*.meta.json` and the node constants in `opensoul/presets.py`. Open Weights Only: no Router or partner-node APIs on the critical path.

## Rules

- Tests must pass on CPU (`OPENSOUL_DRY_RUN=1`).
- UI copy: plain verbs, no model names on the main path (see `DESIGN.md`).
- Only use images of people you have rights to. Keep content SFW.
- Do not commit model weights, tokens, or personal info.
- Code is Apache-2.0. By contributing you agree your contribution is licensed the same way.
