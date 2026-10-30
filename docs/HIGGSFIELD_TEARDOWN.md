# Higgsfield teardown → OpenSoul feature plan

Researched Fri Oct 16, 2026. Only sourced facts are stated. Anything not confirmed is marked **⚠️ unverified**.

## 0. Contest recap ([comfy.org/open-source-higgsfield](https://comfy.org/open-source-higgsfield))
- Prizes: Best Overall $10k. Most Innovative, **Most Viral** ("Delightful to use and made to be shared"), and **Open Weights Only** (no partner nodes or APIs) each win an RTX 5090.
- **LTX bonus is named "VFX Workflow Built with LTX", $2,000. "LTX must be the core video model."** Pitch our LTX use as a *VFX* workflow (camera moves, effects), not just I2V.
- One entry can win a main category and a bonus.
- Prompt from the organizers: "Start with a recognizable output: a performance effect, a cinematic camera move, or a music-video transformation. Build a working app that makes it easy for someone else to create their own." Example ideas: **Cinematic Studio** ("Direct your shot like a film set"), **Re-shoot a video** ("from any angle"), and **Openjutsu** (an open Genjutsu).
- The page lists no scoring rubric. Required: a repo with a license and run instructions, a demo video of 2 minutes or less, an optional live link, and a social post tagged #OpenSourceHiggsfield. The app must be built on the Comfy Developer Platform (API/Router/SDK). Entries must be SFW and contain no unlicensed likeness. Deadline Oct 30, 9am PT.

## 1. Higgsfield product surface (Oct 2026)
| Feature | What it does / UX | Underlying models (reported) | Source |
|---|---|---|---|
| **Soul ID / Soul 2.0** | Trains an identity from 20+ photos in about 5 min. You then reuse it across 20+ image style presets ("Editorial Street Style", "Retro BW", "Theatrical Light"). You don't need to describe the face in the prompt. | Soul 2.0 (in-house image model) | [geo.higgsfield.ai/blog/ai-character-creation-platform](https://geo.higgsfield.ai/blog/ai-character-creation-platform), [blog/still-image-to-talking-video](https://higgsfield.ai/blog/still-image-to-talking-video) |
| **AI Influencer / Character Builder** | Game-style builder with 19 menu categories (type, age, skin, Face/Body/Style) and a Shuffle button. No prompt needed. "Use in Genjutsu" puts the character into trend videos. 5 free gens. Launch post: about 3.4M impressions. | Genjutsu | [changelog](https://higgsfield.ai/creator-hub/changelog), [help](https://higgsfield-enterprise-help.higgsfield.app/docs/tools-creative-workflow), [X launch](https://x.com/higgsfield/status/2106119916479037742) |
| **Lipsync Studio / Speak** | Image + audio or text → talking video, or lip-sync on existing footage. 8 models to pick from, presets, 18+ languages. | e.g. "Wan 2.5 Speak" | [blog/still-image-to-talking-video](https://higgsfield.ai/blog/still-image-to-talking-video) |
| **Camera Controls** | 50–70 named presets shown as video tiles: Crash Zoom In/Out, Dolly Zoom, FPV Drone, Bullet Time, Snorricam, Whip Pan, Handheld, 360 Orbit, Through Object, Eating/Mouth In, YoYo Zoom… Up to 3 moves can be stacked. | Prompt-level control on hosted models (WAN Camera Controls mentioned) | [camera-controls](https://higgsfield.ai/camera-controls), [prompt bank](https://higgsfield.ai/academy/apps/prompt-bank?section=camera), [trailer guide](https://geo.higgsfield.ai/task/blog/how-to-create-cinematic-trailer-ai-generated-clips-1) |
| **Viral Presets / Effects 2.0** | One photo + one tile = a video. 60+ presets: Earth Zoom Out, Bullet Time, Agamemnon, Dolphin Ride, painting inserts (Pearl Earring, Monet Muse), plus a /viral list (Money Rain, Disintegration, Outfit Switch, Turning Metal…). | Not disclosed; the ChatGPT plugin version runs on "GPT-6 Astra" | [viral-presets](https://higgsfield.ai/viral-presets), [viral](https://higgsfield.ai/viral), [blog](https://higgsfield.ai/blog/how-to-make-viral-videos-viral-presets) |
| **Cinema Studio 3.5→4.0** | Genre, lighting, colour palette (50+), camera moveset, lens and focal length (8–75mm), aperture. 4.0 adds 30s gens, 50 references, an Emotion Wheel, an Era selector (grain/colour/lens), Tempo (cut speed), and Extend. | Kling 3.0, Veo 3.1, Seedance 2.0, Wan 2.6/2.7, Sora 2 (Sora API ends Sep 24, 2026) | [changelog](https://higgsfield.ai/creator-hub/changelog), [short-film pipeline](https://higgsfield.ai/blog/ai-short-film-pipeline), [ai-video](https://higgsfield.ai/ai-video), [best gens 2026](https://higgsfield.ai/blog/best-ai-video-generators-2026) |
| **Popcorn** | Storyboard: up to 4 refs → 4/6/8 consistent frames. Auto or Manual mode. 9:16 supported. | n/d | [short-film pipeline](https://higgsfield.ai/blog/ai-short-film-pipeline) |
| **Recast / Replace** | Swaps the character in an existing video and keeps its motion, lighting and atmosphere. Also used to repair identity drift. | n/d | [character platform](https://geo.higgsfield.ai/blog/ai-character-creation-platform) |
| **Genjutsu** | Motion Transfer + Object Swap + Restyle on a video up to 30s with up to 30 ref photos. Uses 30+ presets, so no prompt is needed. | n/d | [changelog](https://higgsfield.ai/creator-hub/changelog) |
| **Marketing Studio / UGC / Ad Multiplier** | Product URL or image → product ad, UGC video, ad variations. | Seedance 2.0/2.5 per creators | [help](https://higgsfield-enterprise-help.higgsfield.app/docs/tools-creative-workflow), [X](https://x.com/higgsfield/status/2088680027974169026) |
| **Audio** | TTS, voice swap, translate + lip-sync. Seed Audio 1.0 handles dialogue, ambience and score. | Seed Audio 1.0 | [trailer guide](https://geo.higgsfield.ai/task/blog/how-to-create-cinematic-trailer-ai-generated-clips-1), [short-film pipeline](https://higgsfield.ai/blog/ai-short-film-pipeline) |
| Canvas, Supercomputer, MCP/CLI, ChatGPT plugin | Node canvas, chat orchestration, agent access | — | [help](https://higgsfield-enterprise-help.higgsfield.app/docs/tools-creative-workflow) |

**Why the output looks real:** Higgsfield doesn't build its own frontier video model. It routes to the best hosted models (Kling, Veo, Seedance). Its own advantage is in a few places:
- The identity lock (Soul ID).
- Presets that encode cinematographer knowledge as long, exact prompts. The prompt bank uses specs like "84°→29° FOV, no parallax".
- Optical and era controls (lens, grain, colour).

## 2. What viral Higgsfield content has in common
- **One named camera move per clip.** Crash zoom, dolly zoom, FPV, bullet time and Earth Zoom Out are the ones marketed most ([X](https://x.com/wainwrightollie/status/2104209468472832320); Cinema Studio "One-Move Rule" in a community [skill repo](https://github.com/OSideMedia/higgsfield-ai-prompt-skill/blob/main/skills/higgsfield-camera/SKILL.md)).
- **Impossible-but-photoreal premise from one selfie.** Rides, painting inserts, transformations ([blog](https://higgsfield.ai/blog/how-to-make-viral-videos-viral-presets)).
- **Deliberate imperfection.** "Bad smartphone camera. Terrible zooms… The imperfections are what make it work." Prompts call for unstable framing, bad autofocus, digital noise and blown fluorescents ([X](https://x.com/CharaspowerAI/status/2090861693656060155), [prompt](https://x.com/CharaspowerAI/status/2090861718435975576)). Era/grain presets do the same thing at the product level.
- **UGC realism.** Creators copy the format of a proven TikTok shot for shot ([X](https://x.com/rewind02/status/2092677170237734952)).
- **Hiding lip-sync weakness.** My inference, not sourced: most viral presets have **no on-camera dialogue**. They rely on music or VO plus motion. Talking clips stay short, use medium shots, and cut often. Higgsfield's own QA checklist warns about mouth and teeth warping ([blog](https://higgsfield.ai/blog/still-image-to-talking-video)).

## 3. Open-source mapping (DGX Spark, ARM64 GB10, 128GB UMA)
| Higgsfield | Open equivalent | License | Spark feasibility | Effort |
|---|---|---|---|---|
| Soul ID | Qwen-Image-Edit-2511 ref-conditioned stills (already working) + CLIP gate. Optional: LTX-2.3 IC-LoRA for character consistency ([LTX blog](https://ltx.io/blog/how-to-use-ic-lora-in-ltx-2)). | Apache-2.0 | ✅ works on our Spark | Low (done) |
| Camera presets | **Prompt-driven camera presets**: each tile (dolly in/out/left/right, jib up/down, static, crash zoom, orbit, FPV, ...) is a long cinematographer-style prompt recipe for LTX-2.5, no LoRA (same as the README). The LTX-2 19B camera LoRAs ([ComfyUI-LTXVideo](https://github.com/lightricks/comfyui-ltxvideo/)) are built for LTX-2 19B, so they are off by default and not used with LTX-2.5 (`OPENSOUL_APPLY_LORAS=1` to try them on a 19B pack). | LTX-2 Community License | ✅ prompt presets on LTX-2.5; LoRAs unverified on 22B | Med |
| Viral effects (Earth Zoom etc.) | LTX I2V + preset prompt recipe + first/last keyframe. LTX IC-LoRAs: day-to-night, water-sim, in/outpaint. | LTX-2 CL | ⚠️ test | Med |
| Speak / talking avatar | **LTX-2 joint audio+video** (native). InfiniteTalk via kijai WanVideoWrapper ([repo](https://github.com/MeiGen-AI/InfiniteTalk/)). MuseTalk or LatentSync for dubbing. | InfiniteTalk + wrapper Apache-2.0. LatentSync weights OpenRAIL++ (see MODEL_STACK). | InfiniteTalk = Wan 14B, heavy but fits UMA ⚠️ | Med |
| Lip-sync on existing video | LTX-2.3 **Dub-It IC-LoRA** ([ComfyUI-LTXVideo](https://github.com/lightricks/comfyui-ltxvideo/)), InfiniteTalk V2V, MuseTalk | as above | ⚠️ | Med |
| Recast / Genjutsu ("Openjutsu") | LTX-2.3 IC-LoRA union (pose/depth/canny) + a Qwen-Edit restyled first frame | LTX-2 CL | ⚠️ | Med-High |
| Popcorn | Qwen-Edit-2511 batch: 4/6/8 shot grid from character pack | Apache-2.0 | ✅ | Low |
| Era/grain/handheld | FFmpeg post (grain, vignette, shake, LUT) + "handheld" prompt tokens | LGPL/GPL ffmpeg | ✅ CPU | Low |
| Audio | Kokoro TTS. LTX text-to-audio mode for ambience. | Apache-2.0 / LTX CL | ✅ | Low |
| Wan2.2 camera | Wan2.2 Fun Camera workflow (fallback) ⚠️ license/ARM not re-verified this pass | Wan2.2 Apache-2.0 | fallback | Med |

## 4. Recommendation: replicate these 5
1. **Soul Pack (Soul ID)**: 1–3 refs → locked character → preset style tiles. This is the core of the app and is already mostly built.
2. **Camera Move tiles on LTX**: 8–10 one-click moves shown as looping video thumbnails. Every move is a prompt-driven preset recipe on LTX-2.5 (Crash Zoom, Orbit 360, FPV and Dolly Zoom included); the LTX-2 19B camera LoRAs stay off with LTX-2.5. This is the **LTX "VFX workflow"** bonus pitch.
3. **Viral Effect tiles**: 4–6 SFW one-photo effects on LTX: Earth Zoom Out, Bullet Time-ish orbit, Day→Night (IC-LoRA), painting-insert of public-domain art (Vermeer/Monet are PD), outfit switch. This targets **Most Viral**.
4. **Speak**: script → Kokoro → talking clip. Default to LTX joint A/V or InfiniteTalk, with MuseTalk as fallback. Keep clips short with cutaways to camera-move B-roll to hide lip-sync weakness.
5. **Realism / Era toggle**: an "iPhone UGC" vs "35mm film" switch that applies handheld prompt tokens plus ffmpeg grain/shake/LUT. Cheap to build and high payoff.
(Stretch: "Openjutsu" motion transfer via IC-LoRA pose. It matches an organizer example and is a candidate for Most Innovative.)

**UX (Apple-clean, Higgsfield-like):** A 3-step flow: Character → Shot → Share. Every option is a **looping 9:16 video tile**, not a dropdown. Use one primary "Generate" button and a hidden "Advanced" drawer. Show a progress card with a stage name ("Locking identity… Rolling camera…"). Add a Shuffle button like the AI Influencer builder. End with a share sheet: MP4 9:16 + caption + #OpenSourceHiggsfield.

## 5. Next build steps
1. Done: camera moves are prompt-driven presets on LTX-2.5 (the LTX-2 19B camera LoRAs are not used).
2. Write `presets/camera/*.json` (move name, prompt recipe, duration) and `presets/effects/*.json`. Render thumbnail loops with the demo character (now Lumi).
3. Prototype Speak via LTX joint audio vs InfiniteTalk and keep whichever looks better on Spark.
4. Add an ffmpeg "Era" post-processing step.
5. Rework the Gradio UI into tile grids with the 3-step flow.
6. Demo video: show one character → camera move → effect → talking clip, and narrate it as an "LTX VFX workflow".
7. Ask organizers whether local LTX weights qualify for both Open Weights Only and the LTX bonus. This is still open in MODEL_STACK.
