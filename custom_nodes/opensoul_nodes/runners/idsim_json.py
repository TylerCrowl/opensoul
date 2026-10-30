#!/usr/bin/env python3
"""ArcFace (insightface buffalo_l) cosine similarity of each image's largest face vs an anchor.
Prints one JSON line: {"scores": [float|null, ...]}. Same method as scripts/idsim.py."""
import json, sys, cv2, insightface
app = insightface.app.FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
app.prepare(ctx_id=-1, det_size=(640, 640))
def emb(img):
    f = app.get(img)
    if not f: return None
    return max(f, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1])).normed_embedding
a = emb(cv2.imread(sys.argv[1]))
if a is None: sys.exit("no face in anchor image")
out = []
for p in sys.argv[2:]:
    e = emb(cv2.imread(p)); out.append(None if e is None else round(float(a @ e), 4))
print(json.dumps({"scores": out}))
