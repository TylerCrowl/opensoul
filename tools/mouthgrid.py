import cv2, sys, os, numpy as np
casc = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))
def run(path, out, n=12):
    cap = cv2.VideoCapture(path); N = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    idx = [int(N*(0.04+0.92*i/(n-1))) for i in range(n)]
    tiles=[]; last=None; nf=0
    for k in idx:
        cap.set(cv2.CAP_PROP_POS_FRAMES, k); ok, fr = cap.read()
        if not ok: continue
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        fs = casc.detectMultiScale(g, 1.1, 5, minSize=(120,120))
        if len(fs):
            x,y,w,h = max(fs, key=lambda f:f[2]*f[3]); last=(x,y,w,h); nf+=1
        elif last is None:
            tiles.append(np.zeros((180,300,3),np.uint8)); continue
        x,y,w,h = last
        y0=int(y+0.58*h); y1=int(y+1.02*h); x0=int(x+0.18*w); x1=int(x+0.82*w)
        c = fr[max(0,y0):y1, max(0,x0):x1]
        c = cv2.resize(c,(300,180),interpolation=cv2.INTER_CUBIC)
        cv2.putText(c,str(k),(4,16),cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,255,255),1)
        tiles.append(c)
    rows=[np.hstack(tiles[i:i+4]) for i in range(0,len(tiles),4)]
    cv2.imwrite(out, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 90])
    print(os.path.basename(path), "frames", N, "facehits", nf, "/", len(idx))
for p in sys.argv[2:]:
    run(p, os.path.join(sys.argv[1], os.path.basename(p).replace("_ls2.0.mp4","_mouth.jpg")))
