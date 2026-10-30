# tools/

Small review helpers used while picking lip-sync takes (CPU, OpenCV only; no model weights).

| Script | Usage | Output |
|---|---|---|
| `mouthgrid.py` | `python tools/mouthgrid.py <outdir> take1_ls2.0.mp4 ...` | one 4-column mouth-crop grid per take (12 evenly spaced frames) |
| `mouthbig.py` | `python tools/mouthbig.py out.jpg <start> <end> <step> take1.mp4 ...` | one row of large mouth crops per take, frames start..end by step |
| `mouthdense.py` | same arguments as `mouthbig.py` | smaller, denser tiles |

Faces are found with OpenCV's bundled Haar cascade; the crop is the lower 40% of the largest face box.
For identity scoring see `scripts/idsim.py` (optional ArcFace, non-commercial `buffalo_l` weights).
