# Experimental templates: music video, UGC ad, product shots, reframe

Status: **stubs behind feature flags, off by default**. With every flag off, New story → Start from a template lists
exactly the templates it always did. Turning a flag on only pre-fills a story's shots (beat, camera move, prompt), like
any other template; nothing else in the app changes.

| Template | File | Flag (set to `1`) | What it pre-fills | Not built yet |
|---|---|---|---|---|
| Music video | `presets/story_templates_flagged/music_video.json` | `OPENSOUL_FEATURE_MUSIC_VIDEO_TEMPLATE` | 16:9 intro, sung verse / chorus close-ups with the camera held still, wide chorus, bridge, outro | song → beat map → bar-aligned shots → sung a2v takes → auto-pick inside the app (the demo music video was made with standalone scripts) |
| UGC ad / talking head | `presets/story_templates_flagged/ugc_ad.json` | `OPENSOUL_FEATURE_UGC_TEMPLATES` | hook to camera, product B-roll, in use, call to action | applying 9:16 and a handheld look automatically; ad-variant batches |
| Product shots | `presets/story_templates_flagged/product_shots.json` | `OPENSOUL_FEATURE_UGC_TEMPLATES` | hero turn, in context, with a person | using an uploaded product photo as every shot's reference |

```bash
OPENSOUL_FEATURE_UGC_TEMPLATES=1 OPENSOUL_FEATURE_MUSIC_VIDEO_TEMPLATE=1 OPENSOUL_DRY_RUN=1 opensoul-ui
```

The `mode`, `aspect` and `status` fields in these files are data for the planned modes; the app does not act on them
yet. Camera ids must be presets in `presets/camera/` (`tests/test_flagged_templates.py`).

## Reframe 9:16 ↔ 16:9 (documented only)

Social clips from any story: crop a finished 16:9 take to 9:16 (or the reverse) around the face, then caption and loop.
Not built: it belongs in the Export step, needs a face-aware crop that follows the face over time, and must keep the
AI-generated label. No code or flag for it exists yet.
