import cv2, sys, os, numpy as np
casc = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))
out=sys.argv[1]; a,b,step=int(sys.argv[2]),int(sys.argv[3]),int(sys.argv[4]); rows=[]
for p in sys.argv[5:]:
    cap=cv2.VideoCapture(p); tiles=[]; last=None
    for k in range(a,b,step):
        cap.set(cv2.CAP_PROP_POS_FRAMES,k); ok,fr=cap.read()
        if not ok: break
        fs=casc.detectMultiScale(cv2.cvtColor(fr,cv2.COLOR_BGR2GRAY),1.1,5,minSize=(120,120))
        if len(fs): last=max(fs,key=lambda f:f[2]*f[3])
        if last is None: tiles.append(np.zeros((150,220,3),np.uint8)); continue
        x,y,w,h=last; c=fr[int(y+0.6*h):int(y+1.0*h), int(x+0.2*w):int(x+0.8*w)]
        c=cv2.resize(c,(220,150),interpolation=cv2.INTER_CUBIC); cv2.putText(c,str(k),(3,14),0,0.45,(0,255,255),1); tiles.append(c)
    r=np.hstack(tiles); cv2.putText(r,os.path.basename(p)[3:14],(3,145),0,0.5,(0,255,0),1); rows.append(r)
w=max(r.shape[1] for r in rows); rows=[np.pad(r,((0,0),(0,w-r.shape[1]),(0,0))) for r in rows]
cv2.imwrite(out,np.vstack(rows),[cv2.IMWRITE_JPEG_QUALITY,90])
