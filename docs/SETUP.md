# Setup: model slots, install plans and swaps

Status: **experimental**. Planning, approval and the checks are tested on CPU with mocks
(`tests/test_setup_engine.py`). Applying a plan for real (downloading models) has not been run on any machine yet.

## Model slots

Every pipeline step is a slot with one active model and ranked alternatives: `image`, `edit`, `video`, `lipsync`,
`music`, `voice`, `upscale`. The data is [presets/model_manifest.yaml](../presets/model_manifest.yaml) (see
[HARDWARE_MEMORY.md](HARDWARE_MEMORY.md#model-manifest-one-slot-per-step)). The app's defaults are unchanged:
VoxCPM2 for new-story voices (Orpheus as the fallback), `ltx_av` for lip-sync, LTX-2.5 int8 for video unless
`LTX_VARIANT=bf16`.

## Plan, approve, apply

```bash
python -m opensoul.setup_engine plan --model ltx25_bf16 --model kokoro     # dry run: prints the plan and its id
python -m opensoul.setup_engine approve <plan_id> --accept-licenses        # YOU run this: prints a one-time token
python -m opensoul.setup_engine apply <plan_id> --token <token> --approve  # runs the plan's commands
python -m opensoul.setup_engine slot voice kokoro                          # plans a slot swap (no downloads)
python -m opensoul.setup_engine slot voice kokoro --plan-id <id> --token <token>   # records it
python -m opensoul.setup_engine rollback                                   # undoes the last slot swap
python -m opensoul.setup_engine health                                     # missing files, problems, disk, memory
```

What a plan contains: the models, the exact `scripts/download_models.sh` groups (with `LTX_VARIANT` / `ALLOW_PICKLE`)
or setup scripts it would run, the download size (an upper bound from the Hub file sizes; files shared between models
are counted once per model), the free disk where models go and whether it fits, which licences need a yes first
(LTX-2.x and the use-restricted class), which downloads are gated on Hugging Face, and which slots change.

Guardrails:

- **Dry run first, always.** Making a plan writes one JSON file under the app's data folder (`setup/plans/`) and
  nothing else.
- **Approval is the user's.** `approve` mints a token; only its sha256 is stored, it expires after 30 minutes and works
  once. There is no approve route in the app's API and no approve tool in the MCP server, so an agent can prepare a
  plan but can't approve it. If the plan file changes after approval, apply refuses it.
- **Explicit flag.** Apply needs both the token and `--approve` (`approve: true` over the API).
- **Preview mode** (`OPENSOUL_DRY_RUN=1`, the default) apply only reports what it would run.
- **Licences.** Blocked licences (non-commercial, research-only) are never installed; candidates not in the app yet
  can't be installed. `--commercial allowed|open_only` limits a plan to commercial-use licences.
- **No system changes.** The commands are the repo's own download and setup scripts, run without a shell; no sudo,
  no network, firewall or driver settings. Every plan, approval, command and slot change goes to `setup/log.jsonl`.
- **Slot swaps are a record for now.** `settings/slots.json` holds the active model per slot with a one-step
  rollback. The render path does not read it yet (Phase 2), so existing stories and defaults are unaffected.

## Models screen (in the app)

The **Models** tab (first in the tab bar, right before Characters; `?models=1` or `?tab=models`, and Settings keeps a
small **Open Models** link, the way in from `?ui=classic`) shows every slot with its active model first and the alternatives: licence
and commercial-use badge, memory need, a fit badge for this computer, download size, installed / in the app / not in
the app yet, and platforms (`app/web/static/models.js`, data from `GET /api/hardware/models`). In preview mode its
**Preview as** menu is the picker's (`?simulate=`), so the fit badges can show e.g. a 64 GB Mac; fit is advisory only
(the computer's tier figure when the picker names the model there, else the smallest measured or estimated figure,
against one GPU's memory, unified memory, or about three quarters of a Mac's memory). **Commercial use only** filters
with the same `allowed` / `open_only` classes as the picker (today every listed model allows commercial use, so only
`open_only`, "no conditions", hides any). **Plan install / swap** calls `POST /api/setup/plan` and shows the dry-run
plan: downloads and commands, the disk check, licences to accept and slot changes. The page never approves: it shows
the exact `python -m opensoul.setup_engine [--data <dir>] approve <plan_id> [--accept-licenses]` command for you to
copy and run in a terminal (the plan response carries it as `approve_command`). Agents can't approve.

## Agents (MCP)

The MCP server ([MCP.md](MCP.md#setup-tools)) exposes the same steps as `list_hardware`, `recommend_models`,
`plan_install`, `apply_install`, `set_slot` and `health_check`, over `/api/setup/*` (`app/setup_routes.py`). Agents can
plan; only you can approve.

## Not built yet

- Benchmark on install (one tiny job per slot to replace estimates with this machine's numbers): planned, not built.
  It needs the GPU and must not run while other jobs are using it.
- Installing candidates (GGUF, MLX, SeedVR2 and others) needs their workflows and nodes first.
- Per-slot routing to several machines (2 × Spark, remote ComfyUI): Phase 2.
