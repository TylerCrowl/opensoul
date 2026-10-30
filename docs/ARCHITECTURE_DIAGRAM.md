# OpenSoul architecture (diagram)

```mermaid
flowchart LR
  subgraph Browser["Browser UI (app/web)"]
    C[1 · Character] --> S[2 · Shot<br/>tiles · Speak · Era · Shuffle]
    S --> SH[3 · Share<br/>MP4 + caption]
  end

  subgraph Server["FastAPI (app/server.py)"]
    P["/api/presets"]
    G["/api/shot"]
    X["/api/share"]
  end

  subgraph Core["opensoul/"]
    PR[presets.py<br/>tile → prompt + LoRA + node inputs]
    RUN[shot.py run_shot]
    TTS[speak.py · KokoroTTS]
    LS["speak.py · LipSync<br/>musetalk | ltx_av | infinitetalk"]
    V[shot.py · VideoBackend<br/>DryRun | ComfyLtx]
    ERA[era.py · ffmpeg grade]
  end

  subgraph Comfy["Comfy Developer Platform"]
    SDK[comfy-sdk client<br/>comfy_client.py]
    CUI[(ComfyUI + open weights<br/>Qwen · LTX-2.5 · Kokoro · MuseTalk)]
  end

  PRE[(presets/*.json)] --> PR
  S --> P --> PR
  S --> G --> PR --> RUN
  RUN --> TTS --> V --> LS --> ERA
  TTS -. live .-> SDK
  V -. live .-> SDK
  LS -. live .-> SDK
  SDK --> CUI
  SH --> X
```

The shot pipeline runs in order: **voice → video → lip-sync → era**. The voice and lip-sync steps only run when the user typed a line. Dotted edges run only when `OPENSOUL_DRY_RUN=0`; in dry-run every stage uses ffmpeg on CPU, so the full flow works without a GPU.
