import cv2, numpy as np, sys
def trim(path, out, keep=0.35, dbg=None):
    im = cv2.imread(path); h, w = im.shape[:2]
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV).astype(int)
    H, S, V = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    skin = ((H <= 22) | (H >= 170)) & (S > 55) & (V > 90)
    bg = (S < 30) & (V > 150)
    skin = cv2.morphologyEx(skin.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats(skin, 8)
    bgd = cv2.dilate(bg.astype(np.uint8), np.ones((7, 7), np.uint8))
    rm = np.zeros((h, w), np.uint8); found = []
    for i in range(1, n):
        x, y, bw, bh, a = st[i]
        if a < 80 or a > 0.02 * h * w: continue
        comp = (lab == i)
        touch = (bgd[comp] > 0).mean()
        if touch < 0.25: continue          # an ear spike sits against the plain background
        if y > 0.6 * h: continue
        cx = x + bw / 2
        # direction: spike points away from the head centre column
        side = -1 if cx < w / 2 else 1
        xs = np.where(comp.any(0))[0]
        if side < 0: cut = xs.max() - int(keep * (xs.max() - xs.min() + 1)); m = comp & (np.arange(w)[None, :] < cut)
        else: cut = xs.min() + int(keep * (xs.max() - xs.min() + 1)); m = comp & (np.arange(w)[None, :] > cut)
        rm |= m.astype(np.uint8); found.append((int(x), int(y), int(bw), int(bh), int(a), round(float(touch), 2)))
    rm = cv2.dilate(rm, np.ones((5, 5), np.uint8))
    res = cv2.inpaint(im, rm, 7, cv2.INPAINT_TELEA)
    cv2.imwrite(out, res)
    if dbg: d = im.copy(); d[rm > 0] = (255, 0, 255); cv2.imwrite(dbg, d)
    return found
for v in sys.argv[1:]:
    print(v, trim(f"{v}.png", f"{v}_trim.png", dbg=f"{v}_dbg.jpg"))
