# workflows/

ComfyUI **API-format** JSON templates for OpenSoul stages.

| File | Stage | Nodes |
|------|-------|-------|
| `01_character_builder_api.json` | Turnaround / expression sheet (Qwen-Image-Edit-2511) | core |
| `02_consistent_stills_api.json` | Pack-conditioned stills | core |
| `03c_tts_orpheus_api.json` | Orpheus 3B TTS, emotion tags (Speak tab, older stories, no-clip fallback) | `OpenSoulOrpheusTTS` |
| `03_tts_api.json` | Kokoro-82M TTS | `OpenSoulKokoroTTS` |
| `03b_tts_chatterbox_api.json` | Chatterbox TTS | `OpenSoulChatterboxTTS` |
| `04_i2v_ltx_api.json`, `04b_a2v_ltx_api.json` | Image/audio-to-video (LTX-2.5) | core |
| `05_lipsync_api.json` | Lip-sync (LatentSync 1.6, default) | `OpenSoulLatentSync` |
| `06_identity_gate_api.json` | Identity-consistency gate (patch default; `06b` ArcFace) | `OpenSoulIdentityGate` |
| `07_character_sheet_api.json` | One view of the six-view Character Sheet (Qwen-Image-Edit-2511 bf16 + Lightning) + identity gate | core + `OpenSoulIdentityGate` |
| `07t_character_from_text_api.json` | Character Sheet from a text description only: renders the reference portrait (same Qwen-Image-Edit-2511 model, no input image) | core |
| `07z_master_from_text_zimage_api.json` | Text-only master (Create → Describe → Generate master): one original-character portrait from the user's words with **Z-Image-Turbo** (Tongyi-MAI, **Apache-2.0**); files and sampler in `presets/text_master.json`, run by `opensoul/zimage_master.py`. `07t` is the fallback (`OPENSOUL_MASTER_BACKEND=qwen07t`) | core |
| `07b_character_sheet_back_from_side_api.json` | Character Sheet back-view fallback: rotates the sheet's side view (picture 1) to a back view, with the reference as picture 2 | core + `OpenSoulIdentityGate` |
| `08m_song_acestep15_api.json` | Song from lyrics (Music tab, studio mode) with **ACE-Step 1.5 XL Turbo** (ACE-Step, **MIT**); node map in `presets/music_models.json`, run by `opensoul/music/song.py`; files: `./scripts/download_models.sh music`. Not yet validated on a GPU from OpenSoul | core |

`OpenSoul*` nodes live in `custom_nodes/opensoul_nodes`. Every node must be listed in
`node_allowlist.json`: `python scripts/check_workflows.py` (also run by pytest and CI) fails otherwise,
and also fails on any partner/API node. All workflows are run with the Comfy SDK through
`opensoul/comfy_client.py`; see `docs/evidence/COMFY_SDK_PROOF.md`.
