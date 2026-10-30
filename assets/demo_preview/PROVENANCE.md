# Preview mode samples (provenance)

Preview mode ("Try it now") has no GPU, so it can't render. Instead it shows these **samples from a real render**:
stills and short clips from *Spin Cycle*, a music video we made with OpenSoul's own open-model pipeline.

## What ships

- 5 clips (540×960, 24 fps, 3 s each, H.264 + AAC mono) and a poster for each.
- 8 stills (540×960 JPEG).
- Juno Pell's master picture and sheet (`assets/juno_pell/`).
- Total size: about 2.4 MB.

Every picture and clip carries a small burned-in "AI-generated sample" label. The clips keep one metadata comment
("AI-generated video"). No other metadata is kept.

## Where it came from

| | |
|---|---|
| Film | `MV_v2_2.mp4`: the cut that its content audit cleared (0 FAIL, 14 SOFT, 29 PASS, Oct 19 2026) |
| Film sha256 | `bbdb223bdfc0feeb6011db066c5087c2a2e991027a03cb903e223e200364ea6c` |
| Character | Juno Pell, an original adult character (early thirties), made from text only. No photo of a person, no reference image, no closed generator. |
| Content | A laundromat at night that turns into a disco. Tracksuit and suit wardrobe. Nothing sexual, no real person, no brand, no readable text. |
| Built with | `scripts/make_preview_samples.py` (CPU: ffmpeg + Pillow); details in `build.json` |

### Clips

| Files | Shows | Source span |
|---|---|---|
| `clip_folding.mp4` + `clip_folding.jpg` | Juno folds a towel at the laundromat table (wide). | MV_v2_2.mp4, 16.68–19.68 s (one take, no splice) |
| `clip_disco_wide.mp4` + `clip_disco_wide.jpg` | The laundromat turns into a disco; Juno dances (wide). | MV_v2_2.mp4, 27.62–30.52 s (one take, no splice) |
| `clip_sock.mp4` + `clip_sock.jpg` | Juno sings and holds up a lost sock (medium). | MV_v2_2.mp4, 43.97–46.97 s (one take, no splice) |
| `clip_tangerine.mp4` + `clip_tangerine.jpg` | Juno sings in the tangerine suit, disco lights (close). | MV_v2_2.mp4, 79.67–82.67 s (one take, no splice) |
| `clip_washer_wall.mp4` + `clip_washer_wall.jpg` | Juno in the tangerine suit by the glowing washers (wide). | MV_v2_2.mp4, 109.41–112.41 s (one take, no splice) |

### Stills

| File | Source |
|---|---|
| `still_folding.jpg` | MV_v2_2.mp4, frame at 18.5 s |
| `still_washer.jpg` | MV_v2_2.mp4, frame at 26.0 s |
| `still_disco.jpg` | MV_v2_2.mp4, frame at 29.0 s |
| `still_basket.jpg` | MV_v2_2.mp4, frame at 34.5 s |
| `still_sock.jpg` | MV_v2_2.mp4, frame at 45.5 s |
| `still_door.jpg` | MV_v2_2.mp4, frame at 60.8 s |
| `still_tangerine.jpg` | MV_v2_2.mp4, frame at 81.5 s |
| `still_washer_wall.jpg` | MV_v2_2.mp4, frame at 111.0 s |

## Models and licenses (all open; verified Oct 19 2026)

| Stage | Model | License |
|---|---|---|
| Song (the clips' audio) | ACE-Step 1.5 XL-turbo | MIT |
| Singer master | Z-Image-Turbo (text only) | Apache-2.0 |
| Scene stills and sheet views | Qwen-Image-Edit-2511 + Lightning 4-step LoRA | Apache-2.0 |
| Video and lip-sync | LTX-2.5 (audio to video) | LTX-2.x Community License: the output is labelled AI-generated |

Not used: no closed or hosted generator, no voice cloning, no reference audio, no LatentSync, no InsightFace, no
Demucs output.

## Rules

- These files are samples. Preview mode never says that they are the user's own take.
- Do not edit them in place. To change them, run the build script again and update this file.
- `assets/demo_audited/` is a different set (the Lumi demo). Its files descend from closed-generator concept art, so
  none of them is used here and none of them ships.
