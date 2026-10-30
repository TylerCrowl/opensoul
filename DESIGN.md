# OpenSoul — Design system

## Mode
**Operate** — task completion, scanability, earned familiarity.

## Visual world
Apple-clean product UI: light, airy, generous whitespace, system typography, one accent, rounded cards, soft depth. Quiet confidence — never loud tech-demo chrome.

## Typography
- Stack: `-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", system-ui, sans-serif`
- Display / titles: 28–34px, weight 600–700, tracking -0.02em, color `#1d1d1f`
- Body: 15–17px, weight 400, color `#1d1d1f`
- Secondary: `#6e6e73`
- No monospace on the main path; no gradient text; no kickers/eyebrows

## Color
| Token | Value | Use |
|-------|-------|-----|
| `--bg` | `#f5f5f7` | Page |
| `--surface` | `#ffffff` | Cards |
| `--text` | `#1d1d1f` | Primary text |
| `--text-secondary` | `#6e6e73` | Helper |
| `--accent` | `#0071e3` | Primary actions only |
| `--accent-hover` | `#0077ed` | Hover |
| `--border` | `rgba(0,0,0,0.08)` | Hairlines |
| `--success` | `#34c759` | Pass |
| `--danger` | `#ff3b30` | Reject |
| `--shadow` | `0 2px 8px rgba(0,0,0,0.04), 0 12px 40px rgba(0,0,0,0.06)` | Cards |

## Layout
- Max content width ~980px, centered
- Card radius 18px; button radius 980px (pill)
- 3-step progress: Character → Shot → Share. Shot uses 9:16 tile grids (camera moves, viral effects), a Speak tab, an Era toggle, one Generate button, Shuffle, and a collapsed Advanced drawer. Tiles show looping video thumbnails when rendered, otherwise an animated placeholder that mimics the move.
- Generous padding (32–48px in cards); tight groups inside fields

## Motion
150–220ms ease-out on step transitions and button hover only.

## Copy rules
Plain language. Prefer "Make photos" over "Generate stills". Hide model/SDK names under Advanced.
