# Story templates

A template is a starting list of shots for **New story → Start from a template**. Drop a JSON file
here and it shows up in the app (no code change):

```json
{"id": "my-template", "title": "Shown on the card", "blurb": "One line under it", "order": 50,
 "shots": [{"beat": "Shot name", "camera": "static", "prompt": "What happens. {lead} = the story's lead character."}]}
```

- `camera` must be a preset id from `presets/camera/` (unknown ids fall back to `static`).
- `characters` (optional, per shot) names characters; without it a shot casts the story's lead (if one was picked).
- Every shot stays editable in the Storyboard: name, cast, camera, prompt, order, delete.

The built-in **Lumi – Night Shift** template (the demo) lives in `opensoul/storyboard.py` (`DEMO_BEATS`).
