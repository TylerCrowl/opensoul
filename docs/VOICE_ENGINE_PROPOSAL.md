# Voice engine proposal (draft, not adopted)

Status: built. The owner chose VoxCPM2 as the default for new stories after hearing the A/B clips (Oct 22 2026), although the GPU test bars were not all met. Orpheus is the rollback (`OPENSOUL_TTS_DEFAULT=orpheus`), older stories stay on it, and a character with no usable voice clip speaks with it, with a note.

## 1. The problem today

The app can already run three voice engines (Orpheus, Kokoro, Chatterbox), but story shots can only use Orpheus:

- `opensoul/lipsync.py` `dialogue_stages()` has a `tts_backend` argument that defaults to `"orpheus"`, and `app/storyboard_api.py` `_dialogue()` never passes it.
- `opensoul/lipsync.py` `synth_line()` (the **Speak** button, via `app/storyboard_api.py` `speak_line()`) calls `get_tts(name="orpheus")` directly.
- `opensoul/speak.py` `ChatterboxTTS.synthesize()` ignores the `voice` argument, so every character would get the same voice. The node (`OpenSoulChatterboxTTS`) already accepts a `voice_reference`, but nothing sends one.
- A character's voice is just an Orpheus voice id (`opensoul/character_voices.py`). Engines that clone a voice need a reference clip, and there is nowhere to store one.

## 2. Plumbing: one engine choice, end to end

1. **Engine per project.** Add `tts_engine` to the project in `opensoul/storyboard.py` (`Project`). If it's missing, the engine is `orpheus`. New projects take the app default, read from a new `OPENSOUL_TTS_DEFAULT` setting (falling back to `presets/models.yaml` voice `default_backend`).
2. **One resolver.** Change `opensoul/character_voices.py` `voice_for_shot()` to return a small voice spec: `{engine, voice_id, ref_clip, ref_text}`. The project engine wins, unless the character's pack pins one.
3. **Dialogue path.** In `app/storyboard_api.py` `_dialogue()`, pass `tts_backend=spec.engine` and the reference clip to `dialogue_stages()`. In `dialogue_stages()`, put `ref_clip` and `ref_text` into the voice stage inputs, and translate emotion tags for the chosen engine (see §4).
4. **Spoken lines.** `speak_line()` and `synth_line()` take the voice spec instead of a bare voice id. Add the engine and the reference clip's sha256 to the cache key, so changing the engine never replays a stale clip.
5. **Running the voice stage.** In `opensoul/shot.py`, the voice step passes the reference clip to `tts.synthesize()`. `opensoul/speak.py` gets a `ref` argument on every backend (Orpheus and Kokoro ignore it), plus `ChatterboxTTS` sends it as `voice_reference`.
6. **Quick shot.** `opensoul/presets.py` `build_shot_plan()` already takes `tts_backend`. It only needs the same voice spec and the new workflow in `TTS_WORKFLOWS`.

## 3. Reference clips in the character pack, and the migration

- **Pack fields** (`pack.json`, next to the existing `voice_label`): `voice: {engine, orpheus_voice, ref_clip, ref_text, ref_sha256, ref_made_with, consent}`. The clip lives in the pack folder as `voice/ref.wav`: 5–15 s, mono, with its exact transcript.
- **Where a clip may come from**, in order of preference:
  1. A voice designed from a text description. VoxCPM2 can do this with no reference at all.
  2. One of our own engines' outputs.
  3. An upload, only with the rights checkbox ticked.
- **Provenance.** Every clip records which model made it, the seed, the settings and the sha256. No provenance means no render.
- **Migration (no breakage).**
  - Existing projects have no `tts_engine`, so they read as `orpheus`.
  - Existing `character_voices.json` picks are kept as `orpheus_voice`. Lumi keeps tara, Mio leah, Ren zac and Pixel jess.
  - Nothing is converted automatically. A project changes engine only when someone picks a new engine in its settings.
  - When a character without a reference clip is switched, the app offers to make one from its current Orpheus voice. That keeps the timbre close and the clip is our own synthetic audio.
  - `tests/test_voice_backcompat.py` already locks the Orpheus behaviour and stays green.

## 4. VoxCPM2 vs Chatterbox

| | VoxCPM2 | Chatterbox |
|---|---|---|
| License | Apache-2.0 (`hf:openbmb/VoxCPM2@32279effe8c19989596f05d353d1447f51d9e915`). Based on MiniCPM-4, which is Apache-2.0 and not Llama | MIT (`hf:ResembleAI/chatterbox@5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18`) |
| How it clones | From a reference clip ("controllable" mode keeps the timbre and allows a `(style)` prefix; "ultimate" mode adds the transcript for the closest match). It can also design a voice from text alone | From a reference clip (`audio_prompt_path`). An `exaggeration` knob controls intensity. No design-from-text mode |
| Local evidence | It made the Lumi demo voice (the F5b set): 4 lines, voice similarity 0.76–0.88 against the reference, all passing their bars, pitch spread 0.3 semitones. Ranked 2nd of 5 in the blind A/B | No character clip has been made or scored yet. One workflow run succeeded on Oct 16 (generic voice, 15.4 s) |
| Memory | Weights 4.6 GB + 377 MB audio VAE. Vendor says ~8 GB (4090); a public benchmark measured 6.4 GB (5090). **Not measured on the Spark** | Weights 3.2 GB; ~6 GB estimated. Not measured |
| Speed | RTF ~0.26–0.30 reported (4090/5090). Not measured on the Spark | Not measured |
| Audio | 48 kHz, no codec artifacts; needed only light cleanup in the mix | 24 kHz, with a built-in inaudible watermark |
| Integration work | New: a ComfyUI node, a runner and its own Python env, a workflow, a download entry, dry-run stub, tests | Mostly done: node, runner and workflow 03b exist. Only the reference clip still needs passing through |
| Orpheus tags (`<sigh> <laugh> <chuckle> …`) | Not read as tags. Removed: VoxCPM2 gets the plain words only. (A `(style)` prefix was tried, but it is read aloud when the clip and its transcript are the prompt, so the app never sends one.) | Not supported: tags are stripped and only the exaggeration knob is left. Expressiveness drops |
| Model-card use rules | "Strictly forbidden" for impersonation, fraud or disinformation; asks that AI audio be clearly labeled. We already label every export AI-generated | No extra rules beyond MIT. The watermark helps with labeling |
| Rights checkbox | A real person's voice must never be cloned. The checkbox must say "This is my own voice or a voice I have written permission to use; not a real person I'm imitating". Designed voices skip the checkbox | The same checkbox is needed, because it clones too. It has no design mode, so every character starts from a clip someone has to supply |

## 5. Recommendation

**Agree with the lean, with conditions: VoxCPM2 as the default for new projects, but only after §6 passes on the Spark. Keep Chatterbox as the second engine and Orpheus for existing projects.**

Why:

1. It's the only candidate with local proof of character quality: the Lumi demo voice is already VoxCPM2.
2. Designing a voice from text gives every new character a voice without anyone uploading audio. That is the strongest answer to the impersonation rule and the rights checkbox.
3. The Orpheus tags are removed for VoxCPM2 (a style prefix can be read aloud), so no tag text reaches it.
4. Its Apache-2.0 license puts it in the open class, which is cleaner than Orpheus's Llama terms.

What's against it: it is unmeasured on the Spark (memory, speed, and whether it installs on that ARM machine), it has no watermark, and the demo Lumi is about 3 semitones lower than the Orpheus Lumi. That pitch gap is exactly why existing projects must stay on Orpheus. If VoxCPM2 fails the GPU test or won't install, Chatterbox (with a reference clip) is the fallback default, because its integration is nearly done.

**Effort** (no GPU time needed for the code):

| Work | Days |
|---|---|
| Plumbing (§2) | 1 |
| Pack clip, migration, consent UI (§3) | 1 |
| VoxCPM2 node, runner, workflow, dry-run stub, tests | 1–1.5 |
| **Total** | **about 3–3.5** |

The VoxCPM2 work in detail:

- `custom_nodes/opensoul_nodes/nodes.py` gets `OpenSoulVoxCPM2TTS`, with inputs text, reference audio, reference text, style, cfg, steps and seed. Its runner is `runners/voxcpm2_tts.py`, with `load_denoiser=False`.
- Setup gets a `voxcpm2-env` in `scripts/download_models.sh`, pinned to the revision above.
- New workflow `workflows/03d_tts_voxcpm2_api.json` and its `.meta.json`. Add it to `workflows/node_allowlist.json`.
- `opensoul/speak.py` gets `VoxCPM2TTS`, which returns a silent placeholder in dry-run, as the other engines do. `presets/models.yaml` gets a voice backend entry, and `presets/hardware_profiles.yaml` changes `voxcpm2` to `in_app: true`.
- Tests:
  - the tag-to-style mapping
  - the workflow schema
  - the dry-run stub
  - engine plumbing through `_dialogue()` and `speak_line()`
  - migration back-compat
  - a refused render when there is no provenance or consent

## 6. GPU test plan (about 15 minutes of GPU time)

**What to render.**
- Lumi: s04_a, s05_c, s08_cd.
- Mio and Ren: two lines each from the demo story.
- All seven lines at 2 seeds, on VoxCPM2 and on Chatterbox: 28 clips.
- References are the characters' own synthetic clips (Lumi's F5b reference; Orpheus-made references for Mio and Ren).
- Draft audio only, with no video renders.

**What to measure.**
- **Words:** WER with a local Whisper (small.en, as used for the F5b scoring).
- **Voice match:** speaker similarity against the character's reference, using the same scorer as F5b.
- **Loudness:** integrated LUFS and true peak.
- **Lip-sync fit:** clip length against `estimate_seconds()`, and whether it fits the a2v frame count after `padded_seconds()`.
- **Cost:** peak GPU process memory, MemAvailable drop, and RTF.

**Pass bar** (per engine). Every line must pass on at least one seed:
- WER ≤ 10%, and the key words are heard
- similarity ≥ 0.85 (≥ 0.74 for lines under 1.5 s)
- no clipping, and true peak ≤ −1 dBTP after leveling
- duration 0.7–1.4× the estimate, with no truncation in the a2v window
- pitch spread ≤ 3 semitones per character
- peak memory ≤ 12 GB

**Gate rules.**
- Run only with explicit sign-off first.
- One GPU job at a time.
- Start only when the ComfyUI queue is empty and MemAvailable ≥ 30 GB.
- Yield to any running `lumi_*`, `ls_*`, `ms_*`, `mv_*` or `sd_*` tmux session and to ACE-Step jobs. Stop and wait rather than compete.
- Log each start, end and result as one line in the shared GPU queue-notes file in the review folder (outside this repo).

## 7. Risks and rollback

**Risks**
- VoxCPM2 may not install on the Spark's ARM Python and torch.
- Spark memory and speed are unknown until the test.
- The demo Lumi's pitch differs from the Orpheus Lumi.
- The style-prefix mapping can over-act.
- There is no watermark, so we rely on the AI label.
- Someone could misuse an upload for a real person's voice. Mitigations: the consent checkbox, provenance, design-first voices, and a refused render without provenance.
- The model's own denoiser download is avoided (`load_denoiser=False`); if it is ever turned on, it needs a credit.

**Rollback** (no data changes):
- `OPENSOUL_TTS_DEFAULT=orpheus` puts new projects back on Orpheus.
- `OPENSOUL_TTS=orpheus` forces every render to Orpheus, overriding project choices.
- Because existing projects never auto-migrate and the Orpheus voice ids stay in every pack, rolling back changes nothing for them.
