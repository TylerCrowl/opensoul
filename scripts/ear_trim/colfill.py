import cv2, numpy as np, sys
# Re-fill the ear-tip area along hair strands (mostly vertical): blend the nearest clean pixels above and below in each column.
src, dbg, out = sys.argv[1:4]
im = cv2.imread(src).astype(np.float32); d = cv2.imread(dbg)
m = (d[..., 2] > 240) & (d[..., 1] < 20) & (d[..., 0] > 240)
m = cv2.dilate(m.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
o = im.copy(); h, w = m.shape
for x in np.nonzero(m.any(0))[0]:
    col = m[:, x]; ys = np.nonzero(col)[0]
    for y in ys:
        a = y
        while a > 0 and col[a]: a -= 1
        b = y
        while b < h - 1 and col[b]: b += 1
        t = (y - a) / max(b - a, 1)
        o[y, x] = (1 - t) * im[a, x] + t * im[b, x]
o = cv2.GaussianBlur(o, (1, 5), 0) * m[..., None] + o * (~m[..., None])
cv2.imwrite(out, o.astype(np.uint8))
