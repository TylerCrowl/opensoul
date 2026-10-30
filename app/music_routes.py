"""Music tab API: /api/music/...  (docs/MUSIC.md; code: opensoul/music/).

Lyrics -> song (a background job, polled like a take) -> beats, bars and sections -> a shot list cut to the beat ->
shots in a story (the normal Storyboard / Render flow) -> lip-sync takes on the song (the full mix by default; a vocal
stem only when the optional ACE-Step 1.5 XL base splitter is installed) -> a music video export.

Preview mode (OPENSOUL_DRY_RUN, the default): the song is original synthetic audio (a click track and a hum, labelled
preview), the vocal stem is that hum, lip-sync takes mux the vocal slice onto a placeholder clip. With a studio set up, your computer runs
the chosen model's ComfyUI workflow (presets/music_models.json) and the existing lip-sync entry points (opensoul.lipsync).
Mounted by app/server.py with ``app.include_router(music_router)``.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from opensoul import storyboard as sb
from opensoul.music import beats as B
from opensoul.music import lrc as LRC
from opensoul.music import registry as R
from opensoul.music import shotlist as S
from opensoul.music import song as SONG
from opensoul.music import stems as STEMS

router = APIRouter(prefix="/api/music", tags=["music"])
_ID = re.compile(r"^[a-f0-9]{10}$")
_JOBS: dict[str, dict] = {}
_LIP: dict[str, dict] = {}
_LOCK = threading.RLock()
STATES_DONE = ("done", "error", "cancelled")


def _srv():
    import app.server as server  # late import: tests monkeypatch server.DATA

    sb.set_data_dir(server.DATA)
    return server


def _dry() -> bool:
    return _srv()._dry()


def _root() -> Path:
    return _srv().DATA / "music"


def _url(p: Path | None, download: bool = False) -> str | None:
    if p is None or not Path(p).is_file():
        return None
    u = _srv()._file_url(Path(p))
    return u + "&download=1" if download else u


def _start(fn) -> None:
    _srv()._start(fn)


# ---------------------------------------------------------------- song records (memory + song.json on disk)
def _dir(sid: str) -> Path:
    return _root() / sid


def _save(job: dict) -> None:
    d = _dir(job["song_id"])
    d.mkdir(parents=True, exist_ok=True)
    keep = {k: v for k, v in job.items() if k != "cancel"}
    sb.atomic_write_json(d / "song.json", keep)


def _load(sid: str) -> dict:
    if not _ID.match(sid or ""):
        raise HTTPException(404, "That song isn't here any more.")
    with _LOCK:
        job = _JOBS.get(sid)
        if job is None:
            f = _dir(sid) / "song.json"
            if not f.is_file():
                raise HTTPException(404, "That song isn't here any more.")
            job = json.loads(f.read_text(encoding="utf-8"))
            if job.get("state") in ("queued", "running"):  # the server restarted mid-job
                job["state"], job["error"] = "error", "The app restarted while this song was being made. Try again."
            _JOBS[sid] = job
        return job


def _song_json(job: dict) -> dict:
    d = _dir(job["song_id"])
    out = {k: job.get(k) for k in ("song_id", "title", "lyrics", "style", "model", "model_label", "seconds", "seed",
                                    "preview", "state", "stage", "error", "label", "created", "beatmap", "cut", "lrc_source",
                                    "beat_backend", "stems_note", "lines", "credit", "handoffs", "quality")}
    out["done"] = job.get("state") in STATES_DONE
    ok = job.get("state") == "done"
    out["song_url"] = _url(d / "song.wav") if ok else None
    out["vocals_url"] = _url(d / "vocals.wav") if ok and (d / "vocals.wav").is_file() else None
    return out


def _cut(job: dict, *, quality: str = "final", bars_per_shot: int | None = None) -> list[dict]:
    bm = B.BeatMap.from_dict(job["beatmap"])
    lines = [LRC.LyricLine(**ln) for ln in job.get("lines") or []]
    cut = S.shot_list(bm, quality=quality, bars_per_shot=bars_per_shot, lyrics=lines or None)
    return [c.to_dict() for c in cut]


def _estimate_lines(lyrics: str, duration: float) -> list[LRC.LyricLine]:
    """No LRC from the model: spread the lyric lines evenly over the song (labelled 'estimated')."""
    rows = [ln for sec in SONG.parse_lyrics(lyrics) for ln in sec["lines"]]
    if not rows or duration <= 0:
        return []
    span = duration * 0.9
    step = span / len(rows)
    t0 = duration * 0.05
    return [LRC.LyricLine(index=i, start=round(t0 + i * step, 3), end=round(t0 + (i + 1) * step - 0.1, 3), text=t)
            for i, t in enumerate(rows)]


def _make_song(job: dict) -> None:
    sid = job["song_id"]
    d = _dir(sid)

    def stage(text: str) -> None:
        if job.get("cancel"):
            raise _Cancelled()
        job["stage"] = text
        _save(job)

    try:
        job["state"] = "running"
        stage("Writing the song…")
        if job["preview"]:
            r = SONG.placeholder_song(d, lyrics=job["lyrics"], style=job["style"], seconds=job["seconds"], seed=job["seed"])
            job["stems_note"] = STEMS.status(True)["note"]
            lrc_text = Path(r["lrc"]).read_text(encoding="utf-8")
            job["lrc_source"] = "preview"
        else:
            model = R.get(job["model"])
            _gpu_turn(job)
            stage("Writing the song…")
            raw = SONG.run_song_workflow(model, d, lyrics=job["lyrics"], style=job["style"], seconds=job["seconds"],
                                         seed=job["seed"])
            from opensoul import media

            media._run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ar", "48000", str(d / "song.wav")], d / "song.wav")
            stage("Separating the vocal…")
            st = STEMS.status(False)
            job["stems_note"] = st["note"]
            if st["available"]:
                voc = STEMS.extract_vocals(d / "song.wav", d)
                media._run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(voc), "-ar", "48000", str(d / "vocals.wav")],
                           d / "vocals.wav")
            else:
                (d / "vocals.wav").write_bytes((d / "song.wav").read_bytes())
            lrc_file = next(iter(sorted(d.glob("*.lrc"))), None)
            lrc_text = lrc_file.read_text(encoding="utf-8") if lrc_file else ""
            job["lrc_source"] = "model" if lrc_text else "estimated"
        stage("Finding the beat…")
        bm, backend = B.analyze_with(d / "song.wav")
        lines = LRC.parse(lrc_text, duration=bm.duration_s) if lrc_text else _estimate_lines(job["lyrics"], bm.duration_s)
        if not lines and lrc_text:
            job["lrc_source"] = "estimated"
            lines = _estimate_lines(job["lyrics"], bm.duration_s)
        parts = SONG.parse_lyrics(job["lyrics"])
        by_lyrics = LRC.sections_from_lyrics(bm, parts, lines) if job.get("lrc_source") in ("preview", "model") else []
        if by_lyrics:
            bm.sections = by_lyrics  # the lyric parts are known: cut sections where the tag changes
        else:
            LRC.name_sections(bm.sections, parts, lines)
        job["beat_backend"] = backend
        job["beatmap"] = bm.to_dict()
        job["lines"] = [ln.to_dict() for ln in lines]
        stage("Cutting shots to the beat…")
        job["cut"] = _cut(job, quality=job.get("quality") or "final")
        job["state"], job["stage"] = "done", "Ready"
    except _Cancelled:
        job["state"], job["stage"] = "cancelled", "Stopped"
    except Exception as e:  # noqa: BLE001
        job["state"], job["error"] = "error", f"Couldn't make the song: {e}"
        job["stage"] = job["error"]
    _save(job)


class _Cancelled(Exception):
    pass


GATE_LISTER = None  # tests replace the session lister; None = read-only `tmux list-sessions`


def _gpu_turn(job: dict) -> None:
    """Studio GPU gate (opensoul.music.gpu_gate): wait while a session we yield to (mv_* ...) is running."""
    from opensoul.music import gpu_gate as G

    gate = R.load().get("gpu_gate") or {}

    def waiting(names):
        job["stage"] = f"Waiting for the GPU: another render is running ({', '.join(names[:2])})."
        _save(job)

    ok = G.wait_turn(G.patterns_from(R.load()), lister=GATE_LISTER, on_wait=waiting, cancelled=lambda: bool(job.get("cancel")),
                     interval_s=float(gate.get("interval_s", 30)), max_wait_s=float(gate.get("max_wait_s", 7200)))
    if not ok:
        if job.get("cancel"):
            raise _Cancelled()
        raise RuntimeError("the GPU stayed busy with another render; try again later")


# ---------------------------------------------------------------- endpoints
@router.get("/models")
def models():
    """Dropdowns: song models and vocal splitters from presets/music_models.json (only usable ones are offered)."""
    pv = _dry()
    return {"preview": pv, "song": R.choices("song", preview=pv), "stems": R.choices("stems", preview=pv),
            "stems_status": STEMS.status(pv), "stems_studio": STEMS.status(False),
            "analysis": R.choices("analysis", preview=pv)}


class SongIn(BaseModel):
    title: str = ""
    lyrics: str = ""
    style: str = ""
    model: str = ""
    seconds: float = 30.0
    seed: int = 7
    quality: str = "final"


@router.post("/songs")
def make_song(req: SongIn):
    """Start a song (background job: queued -> running -> done | error | cancelled). Poll GET /api/music/songs/{id}."""
    lyrics = (req.lyrics or "").strip()
    if not lyrics and not req.style.strip():
        raise HTTPException(400, "Write some lyrics or describe the song first.")
    try:
        SONG.parse_lyrics(lyrics)
    except SONG.SongError as e:
        raise HTTPException(400, str(e))
    pv = _dry()
    ch = R.choices("song", preview=pv)
    model_id = req.model or ch["default"]
    opt = next((o for o in ch["options"] if o["id"] == model_id), None)
    if opt is None:
        pend = next((p for p in ch["pending"] if p["id"] == model_id), None)
        raise HTTPException(400, f"{pend['label']} isn't ready: {pend['why']}." if pend else (ch["empty_reason"] or "Pick a song model."))
    limit = float(opt["max_seconds"] or 120)
    if not 8 <= req.seconds <= limit:
        raise HTTPException(400, f"Pick a length between 8 and {int(limit)} seconds for {opt['label']}.")
    if not 0 <= req.seed < 2**31:
        raise HTTPException(400, "Pick a seed between 0 and 2147483647.")
    if req.quality not in ("final", "draft"):
        raise HTTPException(400, "Quality is final or draft.")
    sid = uuid.uuid4().hex[:10]
    title = " ".join(req.title.split())[:80] or "Untitled song"
    job = {"song_id": sid, "title": title, "lyrics": lyrics, "style": req.style.strip()[:512], "model": model_id,
           "model_label": opt["label"], "seconds": float(req.seconds), "seed": int(req.seed), "quality": req.quality,
           "preview": pv, "state": "queued", "stage": "Waiting to start…", "error": None, "credit": opt.get("credit") or "",
           "label": title + (" · preview" if pv else ""), "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "handoffs": []}
    with _LOCK:
        _JOBS[sid] = job
    _save(job)
    _start(lambda: _make_song(job))
    return _song_json(job)


@router.get("/songs")
def list_songs():
    root = _root()
    out = []
    for f in sorted(root.glob("*/song.json"), key=lambda p: p.stat().st_mtime, reverse=True) if root.is_dir() else []:
        try:
            j = _load(f.parent.name)
        except HTTPException:
            continue
        out.append({k: j.get(k) for k in ("song_id", "title", "label", "state", "created", "preview", "model_label")})
    return {"songs": out[:50]}


@router.get("/songs/{sid}")
def get_song(sid: str):
    return _song_json(_load(sid))


@router.post("/songs/{sid}/cancel")
def cancel_song(sid: str):
    job = _load(sid)
    if job.get("state") in ("queued", "running"):
        job["cancel"] = True
        job["stage"] = "Stopping…"
    return _song_json(job)


class CutIn(BaseModel):
    quality: str = "final"
    bars_per_shot: int | None = Field(default=None, ge=1, le=8)


@router.post("/songs/{sid}/cut")
def recut(sid: str, req: CutIn):
    """Cut the shot list again (Draft clips are 4 s at most; or a fixed number of bars per shot)."""
    job = _load(sid)
    if job.get("state") != "done":
        raise HTTPException(409, "The song isn't ready yet.")
    if req.quality not in ("final", "draft"):
        raise HTTPException(400, "Quality is final or draft.")
    try:
        job["cut"] = _cut(job, quality=req.quality, bars_per_shot=req.bars_per_shot)
    except ValueError as e:
        raise HTTPException(400, str(e))
    job["quality"] = req.quality
    _save(job)
    return _song_json(job)


class HandoffIn(BaseModel):
    character: str = ""
    project_id: str = ""
    idea: str = ""


def _store() -> sb.Store:
    return sb.Store(_srv().DATA / "projects")


def _sidecar(pid: str, sid: str) -> Path:
    return _store().project_dir(pid) / "music" / f"{sid}.json"


@router.post("/songs/{sid}/handoff")
def handoff(sid: str, req: HandoffIn):
    """Make the shot list real: one shot per cut in the list as shown (Final or Draft), in a story (a new one, with the
    app's default 16:9 frame like every new story, unless project_id is given). Each sung shot
    gets its slice of the vocal (the full mix unless the optional splitter is installed) and the LTX audio+video render plan (opensoul.lipsync.a2v_stage)."""
    from opensoul import lipsync as L
    from opensoul.media import MediaError, ffmpeg_bin
    from opensoul.music import export as X

    job = _load(sid)
    if job.get("state") != "done" or not job.get("cut"):
        raise HTTPException(409, "The song isn't ready yet.")
    character = " ".join(req.character.split())[:60]
    if not character:
        raise HTTPException(400, "Pick who sings.")
    st = _store()
    try:
        if req.project_id:
            p = st.load(req.project_id)
        else:
            p = st.create_project(f"{job['title']} (music video)", character=character)
        cut = [S.CutShot(**c) for c in job["cut"]]
        rows = S.storyboard_shots(cut, character, idea=req.idea)
        before = {s.id for s in p.shots}
        for k in range(0, len(rows), sb.MAX_BATCH):
            st.add_shots(p.id, rows[k:k + sb.MAX_BATCH])
        p = st.load(p.id)
    except sb.NotFound as e:
        raise HTTPException(404, str(e))
    except sb.StoryError as e:
        raise HTTPException(400, str(e))
    new = [s for s in p.shots if s.id not in before]
    d = _dir(sid)
    vocals = d / "vocals.wav"
    shots = {}
    note = ""
    for s, c in zip(new, cut):
        row = {"cut": c.to_dict(), "vocal_slice": None, "render": None}
        if c.lipsync:
            secs = c.render_frames / S.FPS
            if ffmpeg_bin() and vocals.is_file():
                dest = st.project_dir(p.id) / "music" / sid / f"{s.id}_vocal.wav"
                try:
                    X.slice_audio(vocals, c.start_s, secs, dest)
                    row["vocal_slice"] = sb.rel_path(dest)
                except MediaError as e:
                    note = f"Couldn't cut the vocal slices: {e}"
            elif not ffmpeg_bin():
                note = "ffmpeg isn't installed: no vocal slices yet."
            row["render"] = L.a2v_stage(prompt=L.speaker_prompt(s.prompt, character, c.lyric), audio_s=secs,
                                        seed=1000 + c.index, quality=job.get("quality") or "final")
        shots[s.id] = row
    side = _sidecar(p.id, sid)
    side.parent.mkdir(parents=True, exist_ok=True)
    sb.atomic_write_json(side, {"song_id": sid, "title": job["title"], "character": character, "fps": S.FPS,
                                "song": sb.rel_path(d / "song.wav"), "order": [s.id for s in new], "shots": shots})
    job.setdefault("handoffs", []).append({"project_id": p.id, "shots": len(new), "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    _save(job)
    return {"project_id": p.id, "title": p.title, "shots": [{"id": s.id, "beat": s.beat, "lipsync": shots[s.id]["cut"]["lipsync"]}
                                                           for s in new], "note": note, "preview": job["preview"], "aspect": p.aspect,
            "quality": job.get("quality") or "final"}


def _handoff_view(p, side: dict, job: dict) -> dict:
    by_id = {s.id: s for s in p.shots}
    rows = []
    for shot_id in side.get("order") or []:
        s = by_id.get(shot_id)
        if s is None:
            continue
        rows.append({"id": s.id, "beat": s.beat, "lipsync": bool(side["shots"][shot_id]["cut"].get("lipsync"))})
    return {"project_id": p.id, "title": p.title, "shots": rows, "note": "", "preview": job.get("preview"),
            "aspect": p.aspect, "quality": job.get("quality") or "final", "restored": True}


@router.get("/songs/{sid}/handoffs")
def list_handoffs(sid: str):
    """OS-033: the stories this song's shots went to, newest first, as the hand-off reply (so the page can show Open
    the shots, the Sync rows and Export video again after a reload). Stories that no longer exist are left out."""
    job = _load(sid)
    st = _store()
    out, seen = [], set()
    for h in reversed(job.get("handoffs") or []):
        pid = h.get("project_id")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        f = _sidecar(pid, sid)
        if not f.is_file():
            continue
        try:
            p = st.load(pid)
        except sb.NotFound:
            continue
        out.append(_handoff_view(p, json.loads(f.read_text(encoding="utf-8")), job))
    return {"handoffs": out}


def _side(pid: str, sid: str) -> dict:
    f = _sidecar(pid, sid)
    if not f.is_file():
        raise HTTPException(404, "Send this song's shots to a story first.")
    return json.loads(f.read_text(encoding="utf-8"))


class LipIn(BaseModel):
    project_id: str
    shot_id: str


def _lip_json(j: dict) -> dict:
    out = {k: j.get(k) for k in ("lipsync_id", "song_id", "project_id", "shot_id", "state", "stage", "error", "take",
                                  "preview", "label")}
    out["done"] = j.get("state") in STATES_DONE
    out["video_url"] = _url(sb.abs_path(j.get("file"))) if j.get("state") == "done" and j.get("file") else None
    out["poster_url"] = _url(sb.abs_path(j.get("poster"))) if j.get("state") == "done" and j.get("poster") else None
    out["placeholder"] = bool(j.get("placeholder"))
    return out


def _run_lipsync(j: dict, side: dict) -> None:
    from opensoul import lipsync as L
    from opensoul import media
    from opensoul.music import export as X

    st = _store()
    pid, shot_id = j["project_id"], j["shot_id"]
    row = side["shots"][shot_id]
    c = row["cut"]
    try:
        tgt = STEMS.sync_target(STEMS.status(False)["available"])
        j["state"], j["stage"] = "running", f"Syncing the mouth to {tgt}…"
        audio = sb.abs_path(row.get("vocal_slice"))
        if audio is None or not audio.is_file():
            raise RuntimeError("this shot has no audio slice (ffmpeg missing?)")
        p = st.load(pid)
        shot = p.shot(shot_id)
        keeper = shot.keeper_version()
        src = sb.abs_path(keeper.file) if keeper and keeper.file and Path(keeper.file).suffix.lower() in X.VIDEO_EXT else None
        take = st.reserve_take(pid, shot_id)
        out_dir = st.take_dir(pid, shot_id, take)
        out_dir.mkdir(parents=True, exist_ok=True)
        if j["preview"]:
            if src is None or not src.is_file():
                src = media._run(X.segment_cmd(None, c["render_frames"], out_dir / "placeholder.mp4"), out_dir / "placeholder.mp4")
            res = L.lipsync(L.LipSyncRequest(audio=audio, dest=out_dir / "sung.mp4", backend="latentsync", video=src,
                                             speaker=side.get("character", "")), dry_run=True)
            label, kind, placeholder = f"Sung to {tgt} · preview", "preview", True
        else:
            if src is None or not src.is_file():
                raise RuntimeError(f"Render this shot first. Then sync it to {tgt}.")
            res = L.lipsync(L.LipSyncRequest(audio=audio, dest=out_dir / "sung.mp4", backend="latentsync", video=src,
                                             speaker=side.get("character", "")), dry_run=False,
                            installed=L.latentsync_installed())
            label, kind, placeholder = f"Sung to {tgt}", "render", False
        poster = media.first_frame(res.video, out_dir / "poster.jpg")
        v = st.add_version(pid, shot_id, take=take, file=sb.rel_path(res.video), poster=sb.rel_path(poster), kind=kind,
                           placeholder=placeholder, label=label, note=" ".join(res.notes),
                           settings={"music_song": j["song_id"], "lipsync": res.backend, "audio_window": [c["start_s"], c["end_s"]],
                                     "frames": c["frames"]})
        j["take"], j["file"], j["poster"], j["placeholder"] = v.id, v.file, v.poster, placeholder
        j["state"], j["stage"] = "done", "Ready"
    except Exception as e:  # noqa: BLE001
        j["state"], j["error"] = "error", f"Couldn't sync this shot: {e}"
        j["stage"] = j["error"]


@router.post("/songs/{sid}/lipsync")
def lipsync_shot(sid: str, req: LipIn):
    """Lip-sync one sung shot to its slice of the vocal: the full mix by default, the vocal stem only when the optional
    XL base splitter is installed (a background job; poll GET /api/music/lipsync/{id}).
    Preview: the slice is muxed onto the shot's keeper (or a placeholder clip). Studio: LatentSync over the keeper take
    (opensoul.lipsync.lipsync); the LTX audio+video render plan from the hand-off is the other route."""
    _load(sid)
    side = _side(req.project_id, sid)
    row = side["shots"].get(req.shot_id)
    if row is None:
        raise HTTPException(404, "That shot didn't come from this song.")
    if not row["cut"]["lipsync"]:
        raise HTTPException(400, "Nobody sings in this shot.")
    jid = uuid.uuid4().hex[:10]
    j = {"lipsync_id": jid, "song_id": sid, "project_id": req.project_id, "shot_id": req.shot_id, "state": "queued",
         "stage": "Waiting to start…", "preview": _dry(),
         "label": f"Sung to {STEMS.sync_target(STEMS.status(False)['available'])}" + (" · preview" if _dry() else "")}
    _LIP[jid] = j
    _start(lambda: _run_lipsync(j, side))
    return _lip_json(j)


@router.get("/lipsync/{jid}")
def lipsync_status(jid: str):
    j = _LIP.get(jid) if _ID.match(jid or "") else None
    if j is None:
        raise HTTPException(404, "That lip-sync job isn't here any more.")
    return _lip_json(j)


class ExportIn(BaseModel):
    project_id: str
    keep_lines: bool = False  # OS-024: spoken lines play over the song (the song goes quieter under them)
    vertical: bool = False    # OS-040: a 9:16 cut of the music video (each shot cropped to fill the frame)


@router.post("/songs/{sid}/export")
def export_video(sid: str, req: ExportIn):
    """The music video: each shot's keeper trimmed to its cut (shots without one become a dark card of the same
    length), joined in order, with the song as the audio. With keep_lines, the takes of spoken (not sung) shots keep
    their own audio over the song, and the song goes quieter under them."""
    from opensoul.media import MediaError, ffmpeg_bin
    from opensoul.music import export as X

    job = _load(sid)
    side = _side(req.project_id, sid)
    st = _store()
    try:
        p = st.load(req.project_id)
    except sb.NotFound as e:
        raise HTTPException(404, str(e))
    if not ffmpeg_bin():
        raise HTTPException(400, "ffmpeg isn't installed, so OpenSoul cannot make the video.")
    by_id = {s.id: s for s in p.shots}
    items, missing, placeholders, spoken = [], 0, 0, 0
    for shot_id in side["order"]:
        c = side["shots"][shot_id]["cut"]
        s = by_id.get(shot_id)
        v = s.keeper_version() if s else None
        src = sb.abs_path((v.file or v.poster) if v else None)
        from opensoul.export_guard import blocked

        if src is not None and blocked(src):
            src = None
        if src is None:
            missing += 1
        elif v.placeholder:
            placeholders += 1
        talk = bool(req.keep_lines and src is not None and s is not None and (s.line or "").strip()
                    and not c.get("lipsync"))
        spoken += talk
        items.append({"source": src, "frames": c["frames"], "keep_audio": talk})
    out_dir = st.project_dir(p.id) / "exports" / f"music_{time.strftime('%Y%m%d_%H%M%S')}"
    out = out_dir / (f"{sb.slug(job['title'], 'music-video')}{'_vertical' if req.vertical else ''}"
                     f"{'_preview' if job['preview'] or placeholders or missing else ''}.mp4")
    try:
        tall = req.vertical or p.aspect == "9:16"
        X.render(items, sb.abs_path(side["song"]), out, size=(720, 1280) if tall else (1280, 720),
                 fill=req.vertical and p.aspect != "9:16")
    except MediaError as e:
        raise HTTPException(500, f"Couldn't make the video: {e}")
    notes = []
    if missing:
        notes.append(f"{missing} {'shot has' if missing == 1 else 'shots have'} no take yet: "
                     f"{'it shows' if missing == 1 else 'they show'} as a dark card so the music stays in time.")
    if placeholders or job["preview"]:
        notes.append("Preview export: the song and some takes are placeholders.")
    if req.keep_lines:
        notes.append(f"Kept the spoken lines of {spoken} {'shot' if spoken == 1 else 'shots'} over the song."
                     if spoken else "No shot has a spoken line, so the song is the only audio.")
    if job.get("credit"):
        notes.append(job["credit"])
    poster = None
    if not (missing or placeholders or job["preview"]):
        from opensoul import media

        try:
            poster = _url(media.first_frame(out, out_dir / "poster.jpg"))
        except MediaError:
            poster = None
    return {"output_url": _url(out), "download_url": _url(out, download=True), "seconds": round(sum(i["frames"] for i in items) / S.FPS, 2),
            "shots": len(items), "note": " ".join(notes), "aspect": "9:16" if req.vertical else p.aspect, "poster_url": poster,
            "preview": bool(missing or placeholders or job["preview"])}
