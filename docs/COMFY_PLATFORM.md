# What "built on the Comfy Developer Platform" means, and how OpenSoul meets it

Researched Fri Oct 16 2026 from docs.comfy.org. The contest rule (from [comfy.org/open-source-higgsfield](https://comfy.org/open-source-higgsfield)):

> "Your work must be built using the Comfy Developer Platform (Comfy API, Comfy Router, and/or Comfy SDK)"

## The three named pieces (official docs)

| Piece | What it is | Docs |
|---|---|---|
| **Comfy SDK** | Official Python (`comfy-sdk`, MIT) and TypeScript (`@comfyorg/sdk`) clients. The `Comfy` client "runs an API-format ComfyUI workflow end to end: upload assets, submit the graph, follow the job, download outputs". `client.models` in the same package is the Router client. | [Comfy SDKs](https://docs.comfy.org/development/api-development/sdks), [PyPI](https://pypi.org/project/comfy-sdk/), [GitHub](https://github.com/Comfy-Org/comfy-python-sdk) |
| **Comfy API (v2)** | The versioned HTTP API (`/api/v2/jobs`, `/api/v2/assets`) that the SDK speaks. Served by Comfy Cloud, by managed "Comfy API" deployments (`*.run.comfy.app`), and for self-hosted ComfyUI by `comfy-api-proxy`. "Comfy API" is also the product name for managed workflow deployments. | [API versions](https://docs.comfy.org/development/comfy-api/overview), [v2 reference](https://docs.comfy.org/api-reference/v2/overview), [Deploying ComfyUI](https://docs.comfy.org/development/deploy/overview), [Comfy API deployments](https://docs.comfy.org/development/serverless/overview) |
| **Comfy Router** | Hosted partner models (FLUX, Veo, Kling…) at `https://api.comfy.org/v2/models/{provider}/{model}`; paid, needs `COMFY_API_KEY`. | [Router quickstart](https://docs.comfy.org/development/comfy-router/quickstart), [Router API](https://docs.comfy.org/development/comfy-router/api) |

The developer landing page groups these as "Run models (Router)", "Run workflows with the SDKs" and "Deploy ComfyUI workflows" ([ComfyUI for Developers](https://docs.comfy.org/development/overview)).

## Does the SDK targeting a local ComfyUI count?

What the docs say:

- "The same code runs against Comfy Cloud or against a ComfyUI instance you host yourself. Only the base URL changes" ([SDKs](https://docs.comfy.org/development/api-development/sdks)).
- Running Workflows lists three deployment targets for the SDKs / API v2: Comfy API deployment, Comfy Cloud, and "**Self-hosted: Yes, via the API Proxy**" ([Running Workflows](https://docs.comfy.org/development/run-workflows/overview)).
- "A self-hosted ComfyUI serves v2 through comfy-api-proxy … Everything in the SDK guide works the same way against the proxy as against Comfy Cloud" ([API Proxy](https://docs.comfy.org/development/comfyui-server/api-proxy)).
- The same page contrasts this with the raw ComfyUI Server API (`/prompt` + websocket): "Self-hosted instances can also skip the SDK entirely". So the raw server API is **not** the SDK path.

**Conclusion:** using `comfy-sdk` → `comfy-api-proxy` → local ComfyUI is an officially documented Comfy SDK + Comfy API v2 setup. It is the self-hosted deployment target Comfy itself describes. It is also the only route compatible with the **Open Weights Only** category ("No partner nodes or APIs"), because Router is partner models only. **Unverified:** the contest page does not say explicitly whether self-hosted SDK use satisfies the rule, and no published rules page was found. Ask the organizers to confirm; a one-off run on Comfy Cloud or a Comfy API deployment would remove the doubt but needs a paid key (a project decision) and our custom nodes would have to be packaged into a Build.

## How OpenSoul uses it

- `opensoul/comfy_client.py`: the only place GPU work is dispatched. It builds `comfy_sdk.Comfy`, uploads inputs as `core/ASSET`s (`client.assets.from_file`), sets node inputs by id, submits to `/api/v2/jobs`, waits, and downloads outputs. `COMFY_BASE_URL` defaults to the local proxy (`http://127.0.0.1:8189`). Without that default, the SDK would target Comfy Cloud and fail without a key.
- The app's live stills, LTX video, TTS and lip-sync paths all call `run_workflow_file`. The old direct-subprocess TTS/MuseTalk bypasses and the raw `/prompt` smoke script were removed, and `tests/test_workflow_allowlist.py` fails if raw ComfyUI HTTP reappears in `opensoul/`, `app/` or `scripts/`.
- Non-core models (Kokoro, Chatterbox, LatentSync, ArcFace) are wrapped as ComfyUI custom nodes (`custom_nodes/opensoul_nodes`), so they also run *inside* ComfyUI as SDK jobs.
- `scripts/check_workflows.py` + CI fail on any node outside `workflows/node_allowlist.json` or any partner/API node.
- Remaining non-Comfy step: the CPU-only ffmpeg "Era" grade/mux/export in the app.

Evidence of real runs: [evidence/COMFY_SDK_PROOF.md](evidence/COMFY_SDK_PROOF.md).
