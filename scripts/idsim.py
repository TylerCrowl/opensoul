"""ArcFace (insightface buffalo_l) cosine similarity of the largest face in each image/video frame vs an anchor image."""
import sys,cv2,numpy as np,insightface
app=insightface.app.FaceAnalysis(name="buffalo_l",providers=["CPUExecutionProvider"]); app.prepare(ctx_id=-1,det_size=(640,640))
def emb(img):
    f=app.get(img); 
    if not f: return None
    f=max(f,key=lambda x:(x.bbox[2]-x.bbox[0])*(x.bbox[3]-x.bbox[1])); return f.normed_embedding
a=emb(cv2.imread(sys.argv[1]))
for p in sys.argv[2:]:
    if p.endswith(".mp4"):
        c=cv2.VideoCapture(p); n=int(c.get(7)); s=[]
        for i in np.linspace(0,n-1,8).astype(int):
            c.set(1,i); ok,fr=c.read(); e=emb(fr) if ok else None
            if e is not None: s.append(float(a@e))
        print(p.split("/")[-1],"min %.3f mean %.3f (n=%d)"%(min(s),np.mean(s),len(s)) if s else "no face",flush=True)
    else:
        e=emb(cv2.imread(p)); print(p.split("/")[-1],"%.3f"%(a@e) if e is not None else "no face",flush=True)
