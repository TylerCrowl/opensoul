# Writing style and glossary

OpenSoul's user-facing text follows ASD-STE100 (Simplified Technical English) where it fits a web app. This covers
UI copy, error messages that reach the UI, README.md, docs/DESKTOP.md and the HOW_TO_OPEN notes in the packages.

## Rules

- A procedural sentence (an instruction) has 20 words or fewer. A descriptive sentence has 25 words or fewer.
- Use the active voice. Say who does the action: "OpenSoul saves the take", not "The take is saved".
- Write one instruction in each sentence: "Click Extract All. Double-click OpenSoul.cmd."
- Use a simple verb, not a phrasal verb: "start", not "fire up"; "remove", not "leave out".
- Do not use slang or idioms.
- A paragraph has 6 sentences or fewer.
- Use one word for one thing. The glossary below gives the word.

## Glossary

| Use | For | Do not use |
|---|---|---|
| **story** | The thing you make in tabs 1–6 (code and API: `project`) | project (in UI text), film, reel |
| **shot** | One moment of a story, one card on the Shots tab | scene, moment. Exception: a script's "scenes" (INT./EXT.) |
| **take** | One rendered result of a shot | clip, render, v1 / v2 (in sentences) |
| **keeper** | The take that a shot uses in the export | approved take (a different review state), winner |
| **stage** | A place that you reuse across shots, with its plate and angles | location, set, place (as a noun for this thing) |
| **character** | A person in the cast, with a name, look, voice and pictures | Soul Pack (README only, for the saved files), character pack |
| **picture** | A still that you add or that OpenSoul makes | image (except in file-format errors), photo (except a camera photo) |
| **seed** | The number that fixes a result | Variation #, variation |
| **Preview mode** | The mode with no GPU: sample takes, placeholders | dry run, preview (alone). Exception: the Models tab's "dry-run plan" |
| **sample** | A short clip from a real OpenSoul render, shown in Preview mode | stand-in (use that only for a drawn placeholder) |
| **studio** | The computer with a GPU that runs ComfyUI | GPU studio, studio computer, machine, server (for the studio) |
| **computer** | Any computer, for example "this computer" | machine, box, PC (except "Windows PC") |
| **click** | Use a control with the mouse or the keyboard | tap, hit, press (except for keys: "press Return") |
| **select** | Turn on a check box | tick, check |
| **license** | A model or asset license (US spelling) | licence |
| **export** | The MP4 of the story, or the vertical clip of one shot | reel |
| **vertical clip** | One shot as a 9:16 MP4 to post | reel, short (for this export; "a short" is one shot made in **Shorts**) |
| **Shorts** | The top-bar item on the right that makes one shot with no story. "A short" is one shot made there | Quick shot, quick shot, Tools |
| **Music videos** | The top-bar item on the right that makes a song, then shots that follow its beat (code and API: `music`) | Music (alone, for this item), Music tab, Tools |
| **voice clip** | A recording of a voice that a voice engine copies | sample (for audio) |

## Names that stay as they are

Product and model names (ComfyUI, LTX, LatentSync, Qwen-Image-Edit, DGX Spark), file names, code, commands and
environment variables stay exactly as they are, inside `code` marks in docs.

## How we check

The App Tester's STE audit (October 2026) scored each surface. A surface passes at 75% or more. The audit scores
these surfaces: UI copy, errors, README.md, docs/DESKTOP.md and HOW_TO_OPEN (Linux, Mac and Windows).
