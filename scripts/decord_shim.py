"""Minimal local decord shim (ARM64 has no decord wheel): cv2 video, librosa audio."""
import cv2, numpy as np, librosa
class _A:
    def __init__(s,a): s.a=a
    def asnumpy(s): return s.a
class VideoReader:
    def __init__(s,path,ctx=None):
        c=cv2.VideoCapture(path); f=[]
        while True:
            ok,fr=c.read()
            if not ok: break
            f.append(cv2.cvtColor(fr,cv2.COLOR_BGR2RGB))
        s.f=np.stack(f)
    def __len__(s): return len(s.f)
    def __getitem__(s,i): return _A(s.f[i])
    def seek(s,i): pass
class AudioReader:
    def __init__(s,path,ctx=None,sample_rate=16000,mono=True):
        y,_=librosa.load(path,sr=sample_rate,mono=True); s.y=y[None]
    def __getitem__(s,i): return _A(s.y[:,i])
    def __len__(s): return s.y.shape[1]
def cpu(i=0): return None
