import cv2, numpy as np, sys, os
KEEP=float(os.environ.get("KEEP","0.4"))
def trim_side(path, out, keep=KEEP, ymax=0.45, dbg=None):
    im = cv2.imread(path); h, w = im.shape[:2]
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV).astype(int)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    skin = (((H <= 22) | (H >= 170)) & (S > 55) & (V > 90)).astype(np.uint8)
    skin = cv2.morphologyEx(skin, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats(skin, 8)
    big = 1 + int(np.argmax(st[1:, 4]))           # face + neck
    fx = cen[big][0]
    rm = np.zeros((h, w), np.uint8); found = []
    for i in range(1, n):
        x, y, bw, bh, a = st[i]
        if i == big or a < 150 or y > ymax * h or a > 0.01 * h * w: continue
        if cen[i][0] < fx + 0.08 * w: continue
        comp = lab == i
        ys, xs = np.nonzero(comp)
        base = np.array([xs[np.argmax(ys)], ys.max()])      # lowest point = where the ear joins the head
        d = np.hypot(xs - base[0], ys - base[1]); lim = keep * d.max()
        m = np.zeros((h, w), bool); m[ys[d > lim], xs[d > lim]] = True
        rm |= m.astype(np.uint8); found.append((int(x), int(y), int(bw), int(bh), int(a)))
    rm = cv2.dilate(rm, np.ones((5, 5), np.uint8))
    cv2.imwrite(out, cv2.inpaint(im, rm, 9, cv2.INPAINT_TELEA))
    if dbg: dd = im.copy(); dd[rm > 0] = (255, 0, 255); cv2.imwrite(dbg, dd)
    return found
print(trim_side(sys.argv[1], sys.argv[2], ymax=float(sys.argv[3]), dbg=sys.argv[2] + "_dbg.jpg"))
