"""Runs inside a paused-Qwen window. Renders stills then videos per jobs.json. Records results to results.jsonl."""
import json,subprocess,sys,re,math,shutil,os,soundfile as sf,numpy as np
H=os.path.expanduser("~/OpenSoul"); R=f"{H}/rb3"; PY=f"{H}/comfyui-env/bin/python"; RUN=f"{H}/repo/scripts/spark_smoke_still.py"
jobs=json.load(open(sys.argv[1])); out=open(f"{R}/results.jsonl","a")
def run(args):
    p=subprocess.run([PY,RUN,"--min-avail-gb","5"]+args,capture_output=True,text=True,cwd=f"{H}/repo"); print(p.stdout[-800:],p.stderr[-800:],flush=True)
    m=re.findall(r"OUTPUT (\S*) (\S+)",p.stdout); return m[-1] if m else None
for j in jobs:
    if j["type"]=="still":
        o=run(["--workflow",f"{R}/02.json","--image",os.environ.get("REF_SHEET", f"{H}/reference_sheet.jpg"),"--image-node","5","--prompt-node","6","--prompt-key","prompt","--seed-nodes","3","--seed",str(j["seed"]),"--prompt",j["prompt"]])
        if o: shutil.copy(f"{H}/ComfyUI/output/{o[0]}/{o[1]}".replace("//","/"),f"{R}/{j['name']}.png")
    else:
        wf=json.load(open(f"{R}/{j['wf']}"))
        frames=j.get("frames",169)
        if j.get("audio"):
            a,sr=sf.read(f"{R}/audio/{j['audio']}.wav"); dur=len(a)/sr+0.6
            frames=math.ceil(dur*24/8)*8+1; n=int(frames/24*sr); a=np.pad(a,(int(0.25*sr),0))[:n]; a=np.pad(a,(0,n-len(a)))
            fn=f"rb3_{j['audio']}.wav"; sf.write(f"{H}/ComfyUI/input/{fn}",a,sr); wf["60"]["inputs"]["audio"]=fn
        wf["30"]["inputs"]["length"]=frames; wf["32"]["inputs"]["frames_number"]=frames
        if j.get("lora"):
            wf["70"]={"class_type":"LoraLoaderModelOnly","inputs":{"model":["10",0],"lora_name":j["lora"],"strength_model":1.0}}
            wf["34"]["inputs"]["model"]=["70",0]
        if "neg" in j: wf["21"]["inputs"]["text"]=j["neg"]
        tmp=f"{R}/_wf_{j['name']}.json"; json.dump(wf,open(tmp,"w"))
        o=run(["--workflow",tmp,"--image",f"{R}/{j['img']}.png","--image-node","1","--prompt-node","20","--prompt-key","text","--seed-nodes","35,43","--seed",str(j["seed"]),"--timeout","900","--prompt",j["prompt"]])
        if o: shutil.copy(f"{H}/ComfyUI/output/{o[0]}/{o[1]}",f"{R}/{j['name']}.mp4")
    out.write(json.dumps({"name":j["name"],"ok":bool(o)})+"\n"); out.flush()
