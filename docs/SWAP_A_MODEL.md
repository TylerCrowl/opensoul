# Swap a model

OpenSoul runs every GPU stage (sheet, stills, voice, video, lip-sync, identity gate) as a ComfyUI
**API-format** workflow sent through the Comfy SDK. The list of stages, which engine each one uses by
default, and which files each engine needs lives in one place: [`presets/models.yaml`](../presets/models.yaml).
The app's System status panel and the Advanced engine pickers read that file, so a model you add there
shows up as Ready / Missing without touching the UI.

There are two kinds of swap. Pick the one that matches what you are doing.

## A. New weights, same kind of graph (no Python)

Example: a newer Qwen-Image-Edit checkpoint for stills, or a different LTX quantization.

1. **Workflow.** Build the graph in ComfyUI, then *Export (API)*. Save it as `workflows/NN_name_api.json`
   (or edit the existing one) and add a `workflows/NN_name_api.meta.json` next to it:
   ```json
   {"note": "Stage N: what it does. App sets node 1 <input>; output node 9.",
    "status": "See docs/evidence/", "format": "ComfyUI API (prompt) dict"}
   ```
   The `note` must name the input and output node ids the app patches.
2. **Registry.** In `presets/models.yaml`, add a backend under the right stage (or edit the `files:` of the
   existing one). Paths are relative to `$COMFY_DIR/models`, or start with `$OPENSOUL_HOME/`. Give it a
   `license:`. Set `default_backend:` if it should become the default.
3. **Download.** Add the file to the matching group in `scripts/download_models.sh` (pin the sha256 like the
   others). If it comes from a new Hugging Face repo, add a row for that repo to the README
   *Credits and licenses → Licenses* table.
4. **Check.**
   ```bash
   python scripts/check_workflows.py   # nodes allowlisted, no partner/API nodes, every model file is downloadable
   pytest -q                           # includes the license-table and registry tests
   ```

## B. A new engine for a stage (small adapter)

Example: a new TTS model or a new lip-sync model with its own node.

Do steps 1–4 above, plus:

5. **Nodes.** If the graph uses a custom node, put it in `custom_nodes/opensoul_nodes` (or vendor an
   Apache/MIT pack) and list every node class in `workflows/node_allowlist.json`. The workflow check fails
   on any node not on that list.
6. **Adapter.** Voice and lip-sync engines are picked by id (`OPENSOUL_TTS`, `OPENSOUL_LIPSYNC`, or the
   Advanced pickers). Add a short class in `opensoul/speak.py` that calls `_run_sdk("<your workflow>", ...)`,
   register its id in the lookup table and in `TTS_BACKENDS` / `BACKENDS`, and use the **same id** in
   `presets/models.yaml`. `tests/test_registry_code_backends.py` fails if the registry lists a voice or
   lip-sync engine the code can't run.

Today step 6 is the only Python a new engine needs; the goal is to make it a registry field as well.

## Before you pick a model

- Open weights only, no partner or API nodes (contest rule and project rule).
- Check the license and note it in the registry and README. [MODEL_WATCH.md](MODEL_WATCH.md) tracks
  candidates per stage with license, size and whether they fit on the DGX Spark.
- Measure it: [HARDWARE_MEMORY.md](HARDWARE_MEMORY.md) shows how the current stages were measured.
