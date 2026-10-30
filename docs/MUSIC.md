# Music videos

**Music videos** is the item on the right of the top bar (code and API: `music`; it was "Music").

Write lyrics, make a song, and get a shot list cut to its beat. Then send the shots to a story and sync the singer
to the song. Code: `app/music_routes.py` (API), `app/web/static/music.js` / `music.css` (UI), `opensoul/music/`.

**Status:** CPU side done and tested. Nothing in the studio (GPU) path has been run from OpenSoul yet: every song
model is marked `gpu_validated: false` in `presets/music_models.json`.

## Flow

1. **Song.** Lyrics with part tags (`[Verse]`, `[Chorus]`, `[Bridge]`), a style line ("genre, mood, instruments,
   voice, 112 BPM"), a length and a variation number. "Generate song" is a background job, polled like a take.
2. **Beat map.** BPM, beats, bars and sections (Verse / Chorus / Bridge, the same letter for repeated parts).
3. **Shot list.** Whole-bar shots that never split a sung line; the chorus cuts faster, the bridge holds longer. Shot lengths are whole
   24 fps frames, rendered at LTX lengths (8k+1 frames). Draft keeps shots ≤ 4 s, Final ≤ 8 s.
4. **Make the video.** Creates the shots in a new story (16:9, like every new story) or an existing one, writes the audio slice for each shot,
   and starts lip-sync takes through the existing lip-sync entry points (`opensoul.lipsync`). Lip-sync uses the full
   mix by default (the note next to **Sync to the song** says so; the button reads **Sync to the vocal** only when the vocal-only track is set up); the vocal stem is used only when the optional
   ACE-Step 1.5 XL base model is installed.
5. **Export.** Keepers trimmed to the cut, the song as the only audio track.

Use your own words and describe a sound. Don't name real artists or songs, and don't feed in recordings of real
songs: the song models only get original lyrics and a style description.

## Preview mode vs. studio

| | Preview (`OPENSOUL_DRY_RUN`, no GPU) | Studio |
|---|---|---|
| Song | `preview_tone`: an original click track whose bars follow the lyric parts, plus a soft hum on each lyric line, and a matching LRC | the chosen model's ComfyUI workflow (`workflows/08m_song_acestep15_api.json` for ACE-Step) |
| Vocal stem | the preview hum | none by default, so lip-sync uses the full mix and Music videos says "Syncing to the full song (this studio has no vocal-only track)." The vocal-only track needs the optional splitter: ACE-Step 1.5 extract on the XL base model (runner not built yet) |
| Beat grid | built-in tracker (numpy) | `beat_this` when installed and its checkpoint is set, else the built-in tracker |
| Lip-sync | the vocal slice muxed onto the keeper (or a placeholder clip) | LatentSync over the keeper (`workflows/05_lipsync_api.json`); the audio-to-video plan uses `workflows/04b_a2v_ltx_api.json` |

## Models (`presets/music_models.json`)

The dropdown only offers a model that `opensoul/music/registry.py` lets through: enabled, licence confirmed and
allowed, every spec filled in, a runner whose workflow file exists, and a
pinned revision (a git commit sha or a sha256) for anything that isn't OpenSoul's own code. An enabled entry that
fails any of these is a registry error, and the tests fail.

Licence policy: allowed are Apache-2.0, MIT, BSD-2-Clause, BSD-3-Clause, CC0-1.0 and CC-BY-4.0 (CC-BY-4.0 only with a
credit line). The LTX-2 community licences are allowed only on output that carries the AI-generated label.
Non-commercial, research-only, gated-without-redistribution and unlicensed models are blocked. Any other licence is
undecided: the model stays off and `opensoul.music.registry.undecided()` lists it for review.

| Model | Role | Licence | Pinned | State |
|---|---|---|---|---|
| ACE-Step 1.5 XL Turbo | song (default) | MIT (code and weights; the Comfy-Org repack card says Apache-2.0, upstream MIT governs) | `Comfy-Org/ace_step_1.5_ComfyUI_files@6707deb277e9e0907fd9c14ce6b6f1d695c6a3fc`, plus the upstream weight and code commits | enabled, not GPU-validated |
| HeartMuLa-oss-3B | song (second option) | Apache-2.0 at the pinned revisions | `HeartMuLa/HeartMuLa-oss-3B-happy-new-year@41f6fc68490e11dc43fdabaa6b5767946408c903`, `HeartMuLa/HeartCodec-oss-20260123@f889dab0532cfa4bf459f2a3367eb6d346b8eeda` | not enabled: needs a custom node and an API workflow |
| beat_this (CPJKU) | beat grid | MIT (code and weights) | checkpoint sha256 `8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331` | used when installed (studio env) |
| OpenSoul beat finder | beat grid (fallback) | this repo's licence | — | always available |
| ACE-Step 1.5 XL base: extract | vocal stem (optional) | MIT | `ACE-Step/acestep-v15-xl-base@220c1166efbdd9583eafcb12eb160594bbfcb241` | off by default; runner is a stub, untested (extract runs on base models only, not on XL Turbo) |
| Demucs | — | code MIT; **weights research-only** (trained on non-commercial data) | — | blocked: never offered, enabled, downloaded or credited |

Older `HeartMuLa/HeartMuLa-oss-3B` revisions were CC-BY-NC-4.0 (non-commercial). Only the revisions above are
Apache-2.0; never fetch an earlier one.

Models whose weights are non-commercial or under custom licences were left out.

Credit line for videos made with ACE-Step: "Music generated with ACE-Step 1.5 (ACE Studio & StepFun), MIT License,
https://github.com/ace-step/ACE-Step-1.5".

## Setting up the studio side

- **Song model files:** `./scripts/download_models.sh music` fetches the four ACE-Step 1.5 XL Turbo split files
  (about 30 GB) at the pinned Comfy-Org revision and checks each sha256. It is not in the default set.
- **Vocal separation (optional, off by default):** `ACE_XL_BASE=1 ALLOW_PICKLE=1 ./scripts/download_models.sh music`
  also fetches `ACE-Step/acestep-v15-xl-base` (MIT, about 20 GB) at the pinned revision with sha256 checks, for the
  ACE-Step Python env. The app's runner for it is not built yet, so lip-sync uses the full mix.
- **Workflow:** `workflows/08m_song_acestep15_api.json` uses ComfyUI core nodes only. The app sets node 5
  (tags, lyrics, seed, bpm, duration, key, time signature, language), node 7 (seconds) and node 8 (seed), and reads
  node 10. `OPENSOUL_ACE_STEP_WORKFLOW=/path/to/graph_api.json` swaps in another API-format graph with the same nodes.
- **beat_this (optional):** install `beat_this` and torch in the studio's Python env (never in the app's `.venv`),
  put the upstream `final0` checkpoint file somewhere local and set `OPENSOUL_BEAT_THIS_CKPT=/path/to/final0.ckpt`
  (or `runner.checkpoint` in the registry). OpenSoul never downloads it: it checks the file against the pinned
  sha256 and uses the built-in tracker when the file is missing or different.
- **Lyric timing:** when the song runner writes an `.lrc` file next to the audio, shot timing and lip-sync windows
  follow it; otherwise line times are estimated from the lyric parts.
- **GPU gate:** in studio mode a song job waits while a tmux session matching `gpu_gate.yield_to` (default `mv_*`)
  is running, so it never competes with another render for the GPU. It only lists session names.
  `OPENSOUL_GPU_GATE=off` turns it off.

## Shot rules

- Every shot is a whole number of bars (at 120 BPM a bar is 2.0 s) and its label says so ("2 bars"). The bars of
  all shots add up to the song's bars; the preview song is an exact number of bars.
- No shot is shorter than one bar. A pickup before bar 1, or a short tail after the last bar, joins its
  neighbour (the label then reads "2 bars + 0.5 s"); if that would pass the maximum, the neighbour is split on a bar first.
- Bars per shot follow the section: a Chorus cuts every bar, a Verse every 2 bars, a Bridge, Intro or Outro
  holds 4 bars. Without lyric tags, loudness decides. Shots stay within the maximum (4 s Draft, 8 s Final).
- Each lyric line belongs to exactly one shot (the one it overlaps most), and a cut never splits a sung line when
  it can move to a nearby bar line instead. Shots without a line are non-singing cutaways.
- **Make the video** creates exactly the list on screen (Draft or Final).
- Durations are whole frames at 24 fps; each shot is rendered at the next LTX length (8k+1 frames) and trimmed.
- Cameras come from the non-experimental presets in `presets/camera/`, picked by energy, and use the same
  labels as the Shots tab.

## API (`/api/music`)

| Method | Path | What it does |
|---|---|---|
| GET | `/models` | song / stems / beat-grid dropdowns, with the reason a model isn't offered |
| POST | `/songs` | start a song job (title, lyrics, style, model, seconds, seed) |
| GET | `/songs`, `/songs/{id}` | list songs / one song with its beat map and shot list |
| POST | `/songs/{id}/cancel` | stop a queued or running job |
| POST | `/songs/{id}/cut` | recut (quality `draft` / `final`, `bars_per_shot` 1–8 or auto) |
| POST | `/songs/{id}/handoff` | create the shots in a story (new or existing), with vocal slices |
| POST | `/songs/{id}/lipsync`, GET `/lipsync/{job}` | lip-sync one shot to its vocal slice |
| POST | `/songs/{id}/export` | the music video as one MP4 |

## Where it hooks into the app

Full studio only: the Shorts page (`?ui=classic`) never shows Music videos.

`app/server.py` includes the router after the storyboard routes; `app/web/index.html` loads `music.css` and
`music.js`, has a **Music videos** button on the right of the top bar, after a thin line and an empty `#musicView` section that `music.js` fills.
`?music=1` opens Music videos directly.

## Not validated yet (needs a GPU)

- ACE-Step song generation from the app, and whether the ComfyUI nodes write lyric timestamps (LRC).
- ACE-Step 1.5 extract on the XL base model as the vocal splitter (runner still a stub).
- beat_this in the studio env (its Python API is assumed from its README).
- LTX audio-to-video with a vocal slice, LatentSync on singing, and the 8 s Final shot limit.
- HeartMuLa entirely.
