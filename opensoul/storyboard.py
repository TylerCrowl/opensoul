"""Storyboard: a project is an ordered list of shots; every shot keeps every take it ever had.

On disk: ``<root>/<project_id>/project.json`` (atomic writes: temp file + fsync + os.replace) and the
takes' media under ``<root>/<project_id>/shots/<shot_id>/v<n>/``.

Rules this module guarantees (tests in tests/test_storyboard.py):
- Shot order is exactly the order of ``project.shots``; reorder must be a permutation (nothing lost).
- A new take is always appended with a fresh take number (numbers are never reused); nothing is
  overwritten. A take is only removed by ``delete_version(..., confirm=True)``.
- One keeper per shot; export stitches the keepers in shot order.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_LOCK = threading.RLock()


class StoryError(ValueError):
    """A user-facing problem (unknown id, bad order, missing confirm)."""


class NotFound(StoryError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def slug(text: str, fallback: str = "story") -> str:
    import unicodedata

    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:40].strip("-")
    return t or fallback


_DATA_DIR: Path | None = None


def set_data_dir(p: str | Path | None) -> None:
    """The server's DATA dir (OPENSOUL_DATA). Media paths stored as ``data/...`` resolve against it, never the repo."""
    global _DATA_DIR
    _DATA_DIR = Path(p) if p else None


def data_dir() -> Path:
    import os

    return _DATA_DIR or Path(os.environ.get("OPENSOUL_DATA", ROOT / "data"))


def rel_path(p: str | Path | None) -> str | None:
    """Portable form of a media path: ``data/<rest>`` for files under the DATA dir (whatever OPENSOUL_DATA is), repo-
    relative for shipped repo files (assets/, docs/ ...), else absolute."""
    if p is None or p == "":
        return None
    p = Path(p).resolve()
    try:
        return (Path("data") / p.relative_to(data_dir().resolve())).as_posix()
    except ValueError:
        pass
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def within(path: str | Path, root: str | Path) -> bool:
    """True when ``path`` resolves inside ``root``. ``..``, absolute paths and symlinks that leave ``root`` are out.

    The API has no login and listens on this computer, so any other local account can call it. A stored or
    caller-supplied path must not make the server read that account's way into files the OpenSoul user can see.
    """
    try:
        q, r = Path(path).resolve(), Path(root).resolve()
        return q == r or q.is_relative_to(r)
    except (OSError, ValueError):
        return False


def abs_path(p: str | None) -> Path | None:
    """``data/<rest>`` -> the server's DATA dir (so a sandbox copy of a story never reads the repo's real data);
    other relative paths -> the repo (shipped assets).

    Relative paths that leave those trees (``..`` or a symlink) are None. An absolute path is returned as given:
    HTTP handlers that take a path from the caller must also require :func:`within` the data dir or the repo.
    Render code passes absolute paths of files this process just wrote.
    """
    if not p:
        return None
    q = Path(p)
    if q.is_absolute():
        return q
    if q.parts and q.parts[0] == "data":
        candidate = data_dir().joinpath(*q.parts[1:])
    else:
        candidate = ROOT / q
    if within(candidate, data_dir()) or within(candidate, ROOT):
        return candidate
    return None


@dataclass
class Version:
    id: str                      # "v1", "v2", ... (unique within the shot, never reused)
    take: int
    take_id: str                 # "<shot_id>-v<n>"
    file: str | None = None      # main media (mp4 or still)
    poster: str | None = None    # still for the card / filmstrip
    prompt: str = ""             # the full prompt used
    edit: str = ""               # the "What should change?" text that produced this take
    seed: int | None = None
    settings: dict = field(default_factory=dict)
    scores: dict = field(default_factory=dict)
    created: str = field(default_factory=_now)
    kind: str = "render"         # render | preview (dry-run mock) | concept (placeholder still) | frame (start still)
    #                              | upload (the user's own file, OS-064) | card (a text card made on this computer, OS-063)
    placeholder: bool = False
    label: str = ""              # e.g. "Concept image · placeholder"
    status: str = "ready"        # ready | rendering | failed
    note: str = ""
    based_on: str | None = None  # version id this take was regenerated from


@dataclass
class StageAngle:
    """One fixed camera angle of a stage (e.g. "behind the counter"), drawn from the same room as the master plate."""
    name: str
    image: str = ""
    note: str = ""               # what this angle sees, used in the start-frame prompt
    status: str = ""             # "" (ready / no picture yet) | "rendering" | "failed"
    error: str = ""              # why the last render failed (plain words)


@dataclass
class Location:
    """A stage the story returns to (e.g. "Konbini interior"): its stage sheet. The master plate, up to six
    consistent angles of the SAME room, an empty plate and a fixed set description + continuity checklist.
    Start frames of shots set here are edited from the matching angle (or the master) and then plate-locked,
    so the place looks the same in every shot, the way a character sheet keeps a face the same."""
    name: str
    image: str = ""              # master plate (repo-relative or absolute path); the wide / establishing angle
    description: str = ""        # fixed set block, appended to every start-frame prompt of the location
    empty: str = ""              # the same master angle with nobody in it (for compositing actors)
    angles: list[StageAngle] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)
    sheet: str = ""              # the rendered stage-sheet image (contact sheet of all angles)

    def angle(self, name: str) -> StageAngle | None:
        key = " ".join(str(name or "").split()).lower()
        return next((a for a in self.angles if a.name.lower() == key), None) if key else None

    def plate_for(self, angle: str = "") -> str:
        """Picture a start frame should be edited from: the shot's angle if it has one, else the master."""
        a = self.angle(angle)
        return a.image if a and a.image else self.image


@dataclass
class Shot:
    id: str
    beat: str
    prompt: str = ""
    characters: list[str] = field(default_factory=list)
    camera: str = "static"
    camera_moves: list[str] = field(default_factory=list)  # 2-3 stacked moves in order ([] = just `camera`)
    location: str = ""           # name of a Project.locations entry ("" = none)
    stage_angle: str = ""        # angle of that stage ("" = the master plate)
    # Dialogue (one spoken line per shot; see opensoul/lipsync.py for how it renders)
    line: str = ""               # what's said, with allowed Orpheus tags only: <laugh> <chuckle> <sigh> ...
    speaker: str = ""            # who says it: one of `characters` ("" = the only cast member, if just one)
    voice: str = ""              # Orpheus voice override ("" = the speaker's own voice)
    line_id: str = ""            # script line id, e.g. "l07" ("" = 'lNN' in the beat / shot id, else its position)
    lipsync: bool = True         # Final takes render the mouth to the voice
    lipsync_backend: str = "ltx_av"   # "ltx_av" (joint audio+video) | "latentsync" (after the video)
    mouth_refine: bool = False   # opt-in LatentSync Stage 2 on camera-locked takes (it may pale the lips)
    face_box: list[int] | None = None  # speaker's face on frame 0, [x, y, w, h] output px (latentsync targeting)
    seconds: float = 0.0         # planned length of the shot (OS-059 talking take, OS-061 export cut; 0 = automatic)
    trim_start: float = 0.0      # OS-061: the export uses the keeper from this second on (0 = from the start)
    kind: str = "scene"          # OS-063: "scene" (made by the models) | "card" (title or end card, text drawn here)
    card_title: str = ""         # the card's big line
    card_sub: str = ""           # the card's small line
    card_bg: str = "black"       # black | white | night | red | #rrggbb
    versions: list[Version] = field(default_factory=list)
    keeper: str | None = None
    next_take: int = 1
    created: str = field(default_factory=_now)

    def version(self, vid: str) -> Version:
        for v in self.versions:
            if v.id == vid:
                return v
        raise NotFound(f"Take {vid} isn't in this shot.")

    def keeper_version(self) -> Version | None:
        return next((v for v in self.versions if v.id == self.keeper), None)


@dataclass
class Project:
    id: str
    title: str
    character: str
    shots: list[Shot] = field(default_factory=list)
    aspect: str = "16:9"
    created: str = field(default_factory=_now)
    updated: str = field(default_factory=_now)
    deleted_shots: list[Shot] = field(default_factory=list)  # deleted shots keep their takes (undo-able)
    locations: list[Location] = field(default_factory=list)
    # Voice engine (opensoul/voice_engine.py). None = a story saved before engines existed: Orpheus, unchanged.
    tts_engine: str | None = None
    # Art look of every picture and video (opensoul/looks.py): "" = not set (photo), "anime", "toon3d", ...
    look: str = ""
    # OS-017: re-render a take whose camera move reads wrong (up to 2 more renders). Off: the take stays, with a note.
    fix_camera: bool = False
    # OS-068: what pictures and takes must not show (opensoul/originality.py). The default list is on unless turned off.
    avoid: str = ""
    avoid_defaults: bool = True

    def location(self, name: str) -> Location | None:
        key = " ".join(str(name or "").split()).lower()
        return next((loc for loc in self.locations if loc.name.lower() == key), None) if key else None

    def shot(self, sid: str) -> Shot:
        for s in self.shots:
            if s.id == sid:
                return s
        raise NotFound("That shot isn't in this story anymore.")

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Project":
        # Fields this build doesn't know (a file saved by a newer build) are ignored, never a crash.
        def shot(s: dict) -> Shot:
            s = _known(Shot, s)
            s["versions"] = [Version(**_known(Version, v)) for v in s.get("versions", [])]
            return Shot(**s)

        d = _known(Project, d)
        d["shots"] = [shot(s) for s in d.get("shots", [])]
        d["deleted_shots"] = [shot(s) for s in d.get("deleted_shots", [])]
        d["locations"] = [Location(**{**_known(Location, loc),
                                      "angles": [StageAngle(**_known(StageAngle, a)) for a in loc.get("angles", [])]})
                          for loc in d.get("locations", [])]
        return Project(**d)


def _known(cls, d: dict) -> dict:
    """Only the keys ``cls`` (a dataclass) accepts."""
    names = {f.name for f in fields(cls)}
    return {k: v for k, v in dict(d).items() if k in names}


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


MAX_BATCH = 60


def clean_cast(names) -> list[str]:
    """Trimmed, de-duplicated (case-insensitive) character names, in order."""
    out, seen = [], set()
    for n in names or []:
        n = " ".join(str(n or "").split())[:60]
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out[:12]


CARD_FIELDS = ("kind", "card_title", "card_sub", "card_bg")


def card_fields(d: dict) -> dict:
    """OS-063: the checked shot kind and card words in ``d`` (missing keys are left out). Raises StoryError."""
    out = {}
    if d.get("kind") is not None:
        if d["kind"] not in ("scene", "card"):
            raise StoryError("A shot is a scene or a card.")
        out["kind"] = d["kind"]
    if any(d.get(k) is not None for k in CARD_FIELDS[1:]):
        from opensoul import cards

        try:
            c = cards.clean(d.get("card_title"), d.get("card_sub"), d.get("card_bg"))
        except cards.CardError as e:
            raise StoryError(str(e)) from None
        out.update({k: v for k, v in c.items() if d.get(k) is not None})
    return out


MAX_TRIM = 60.0


def clean_trim(v) -> float:
    """OS-061: where the export starts in the keeper, in seconds (0 to 60, one decimal). Raises StoryError."""
    if v in (None, ""):
        return 0.0
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise StoryError("Type the start in seconds, for example 1.5.") from None
    if not 0.0 <= f <= MAX_TRIM:
        raise StoryError(f"Set a start from 0 to {MAX_TRIM:g} seconds.")
    return round(f, 1)


MAX_LINE = 500
DIALOGUE_FIELDS = ("line", "speaker", "voice", "lipsync", "lipsync_backend", "mouth_refine", "face_box", "seconds")


def clean_dialogue(d: dict) -> dict:
    """Validate the dialogue fields present in ``d`` (others untouched). Raises StoryError with a plain message."""
    from opensoul.lipsync import check_backend
    from opensoul.orpheus import TagError, check_voice, normalize_tags

    out = {}
    if d.get("line") is not None:
        line = " ".join(str(d["line"]).split())
        if len(line) > MAX_LINE:
            raise StoryError(f"Keep the spoken line under {MAX_LINE} characters. Use two shots for a longer line.")
        try:
            out["line"] = normalize_tags(line) if line else ""
        except TagError as e:
            raise StoryError(str(e)) from None
    if d.get("speaker") is not None:
        out["speaker"] = " ".join(str(d["speaker"]).split())[:60]
    if d.get("voice") is not None:
        v = str(d["voice"]).strip().lower()
        try:
            out["voice"] = check_voice(v) if v else ""
        except ValueError as e:
            raise StoryError(str(e)) from None
    if d.get("lipsync") is not None:
        out["lipsync"] = bool(d["lipsync"])
    if d.get("seconds") is not None:
        from opensoul.voice_shape import clean_seconds

        try:
            out["seconds"] = clean_seconds(d["seconds"])
        except ValueError as e:
            raise StoryError(str(e)) from None
    if d.get("mouth_refine") is not None:
        out["mouth_refine"] = bool(d["mouth_refine"])
    if d.get("lipsync_backend") is not None:
        try:
            out["lipsync_backend"] = check_backend(str(d["lipsync_backend"]))
        except ValueError as e:
            raise StoryError(str(e)) from None
    if "face_box" in d and d["face_box"] is not None:
        fb = d["face_box"]
        if fb == []:
            out["face_box"] = None
        else:
            try:
                fb = [int(x) for x in fb]
            except (TypeError, ValueError):
                fb = []
            if len(fb) != 4 or fb[2] <= 0 or fb[3] <= 0 or min(fb[:2]) < 0:
                raise StoryError("The face box is x, y, width, height in pixels.")
            out["face_box"] = fb
    return out


def _speaker_in_cast(s: "Shot", explicit: bool) -> None:
    """The speaker must be in the shot's cast (spelled as in the cast). A cast change silently drops a gone speaker."""
    if not s.speaker:
        return
    hit = next((c for c in s.characters if c.lower() == s.speaker.lower()), None)
    if hit:
        s.speaker = hit
    elif explicit:
        raise StoryError(f"{s.speaker} isn't in this shot. Add them to the cast or pick someone else to speak.")
    else:
        s.speaker = ""


def _carry_speaker(s: "Shot", old_cast: list[str]) -> None:
    """OS-053: when the speaker's cast chip is changed to a different character (one name out, one name in), that
    character speaks the line."""
    new = s.characters or []
    if not s.speaker or any(c.lower() == s.speaker.lower() for c in new):
        return
    old = {c.lower() for c in old_cast}
    added = [c for c in new if c.lower() not in old]
    if len(added) == 1 and s.speaker.lower() in old:
        s.speaker = added[0]


def _sole_speaker(s: "Shot") -> None:
    """OS-053: a line with one person in the cast is theirs. The saved speaker is the one the page shows."""
    if s.line and not s.speaker and s.characters and len(s.characters) == 1:
        s.speaker = s.characters[0]


def check_shots(shots: list[dict]) -> list[Shot]:
    """Validate a batch of shots (all or nothing) before anything is saved."""
    if len(shots) > MAX_BATCH:
        raise StoryError(f"Up to {MAX_BATCH} shots at a time.")
    rows = []
    for d in shots:
        beat = " ".join(str(d.get("beat") or "").split())[:120]
        if not beat:
            raise StoryError("Every shot needs a name.")
        cast = d.get("characters")
        r = Shot(id=_id("s"), beat=beat, prompt=str(d.get("prompt") or "")[:2000],
                 characters=None if cast is None else clean_cast(cast), camera=str(d.get("camera") or "static"),
                 **clean_dialogue(d), **card_fields(d))
        if r.characters is not None:
            _speaker_in_cast(r, explicit=True)
            _sole_speaker(r)
        rows.append(r)
    return rows


class Store:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    # ------------------------------------------------------------ projects
    def _file(self, pid: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", pid or ""):
            raise NotFound("Unknown story.")
        return self.root / pid / "project.json"

    def project_dir(self, pid: str) -> Path:
        return self._file(pid).parent

    def exists(self, pid: str) -> bool:
        try:
            return self._file(pid).is_file()
        except NotFound:
            return False

    def load(self, pid: str) -> Project:
        f = self._file(pid)
        if not f.is_file():
            raise NotFound("Unknown story.")
        try:
            return Project.from_dict(json.loads(f.read_text(encoding="utf-8")))
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            raise StoryError(f"The story file for {pid!r} can't be read ({type(e).__name__}: {e})."[:300]) from e

    def save(self, p: Project) -> Project:
        p.updated = _now()
        atomic_write_json(self._file(p.id), p.to_dict())
        return p

    def list_projects(self) -> list[Project]:
        return self.scan()[0]

    def scan(self) -> tuple[list[Project], list[dict]]:
        """(readable projects oldest first, unreadable files as {"id", "error"}). A broken file never takes
        the list down; it is reported so the app can say which story couldn't be opened."""
        if not self.root.is_dir():
            return [], []
        out, broken = [], []
        for f in sorted(self.root.glob("*/project.json")):
            try:
                out.append(Project.from_dict(json.loads(f.read_text(encoding="utf-8"))))
            except (ValueError, TypeError, KeyError, AttributeError, OSError) as e:
                broken.append({"id": f.parent.name, "error": f"{type(e).__name__}: {e}"[:300]})
        return sorted(out, key=lambda p: p.created), broken

    def create_project(self, title: str, character: str = "", pid: str | None = None, aspect: str = "16:9") -> Project:
        """A new, empty story. ``character`` is the optional lead (new shots cast them by default)."""
        title = " ".join(str(title or "").split())[:80] or "Untitled story"
        character = " ".join(str(character or "").split())[:60]
        with _LOCK:
            pid = pid or slug(title)
            base, i = pid, 2
            while self.exists(pid):
                pid, i = f"{base}-{i}", i + 1
            taken = {p.title.lower() for p in self.list_projects()}
            name, i = title, 2
            while name.lower() in taken:  # two stories never share a name in the picker
                name, i = f"{title} {i}", i + 1
            from opensoul.voice_engine import default_for_new

            return self.save(Project(id=pid, title=name, character=character, aspect=aspect,
                                     tts_engine=default_for_new()))

    def _edit(self, pid: str, fn):
        with _LOCK:
            p = self.load(pid)
            res = fn(p)
            self.save(p)
            return p if res is None else res

    def update_project(self, pid: str, title: str | None = None, character: str | None = None,
                       tts_engine: str | None = None, look: str | None = None,
                       fix_camera: bool | None = None, avoid: str | None = None,
                       avoid_defaults: bool | None = None) -> Project:
        """Rename a story, change its lead, its voice engine or its look. The id (and folder) never changes."""
        def fn(p: Project):
            if avoid is not None:  # OS-068
                from opensoul import originality

                p.avoid = originality.clean(avoid)
            if avoid_defaults is not None:
                p.avoid_defaults = bool(avoid_defaults)
            if fix_camera is not None:
                p.fix_camera = bool(fix_camera)
            if look is not None:
                from opensoul import looks

                try:
                    p.look = looks.check(look)
                except ValueError as e:
                    raise StoryError(str(e))
            if tts_engine is not None:
                from opensoul.voice_engine import check

                try:
                    p.tts_engine = check(tts_engine)
                except ValueError as e:
                    raise StoryError(str(e))
            if title is not None:
                t = " ".join(str(title).split())[:80]
                if not t:
                    raise StoryError("Give the story a name.")
                if any(o.id != p.id and o.title.lower() == t.lower() for o in self.list_projects()):
                    raise StoryError(f"You already have a story called {t!r}. Pick another name.")
                p.title = t
            if character is not None:
                p.character = " ".join(str(character).split())[:60]
        return self._edit(pid, fn)

    # ------------------------------------------------------------ shots
    def add_shot(self, pid: str, beat: str, prompt: str = "", characters: list[str] | None = None,
                 camera: str = "static", index: int | None = None, **dialogue) -> Shot:
        """``characters=None`` casts the story's lead (if any); ``[]`` means nobody (a scene-only shot)."""
        beat = " ".join(str(beat or "").split())[:120]
        if not beat:
            raise StoryError("Give the shot a short title.")
        dia = clean_dialogue({k: v for k, v in dialogue.items() if k in DIALOGUE_FIELDS})
        extra = card_fields(dialogue)

        def fn(p: Project):
            cast = clean_cast(characters) if characters is not None else ([p.character] if p.character else [])
            if extra.get("kind") == "card" and characters is None:
                cast = []  # a card has nobody in it
            s = Shot(id=_id("s"), beat=beat, prompt=str(prompt or "")[:2000],
                     characters=cast, camera=camera or "static", **dia, **extra)
            _speaker_in_cast(s, explicit=True)
            if index is None or index >= len(p.shots):
                p.shots.append(s)
            else:
                p.shots.insert(max(0, int(index)), s)
            return s
        return self._edit(pid, fn)

    def update_shot(self, pid: str, sid: str, **fields) -> Shot:
        allowed = {"beat", "prompt", "characters", "camera", "location", "stage_angle", "trim_start", "kind"}
        card = {k: v for k, v in card_fields(fields).items() if k != "kind"}  # OS-063
        moves = fields.get("camera_moves")
        if moves is not None:  # stacked moves win over a plain camera; one move is stored as just `camera`
            from opensoul import camera_moves as cm

            try:
                moves = cm.check(moves)
            except cm.MoveError as e:
                raise StoryError(str(e)) from None
            fields = {**fields, "camera": moves[0]}
        elif fields.get("camera") is not None:
            moves = []  # picking a single move clears a stack
        dia = clean_dialogue({k: v for k, v in fields.items() if k in DIALOGUE_FIELDS})

        def fn(p: Project):
            s = p.shot(sid)
            old_cast, old_speaker = list(s.characters or []), s.speaker
            for k, v in dia.items():
                setattr(s, k, v)
            for k, v in card.items():
                setattr(s, k, v)
            if moves is not None:
                s.camera_moves = moves if len(moves) > 1 else []
            for k, v in fields.items():
                if k in allowed and v is not None:
                    if k == "beat":
                        v = " ".join(str(v).split())[:120]
                    elif k == "characters":
                        v = clean_cast(v)
                    elif k == "prompt":
                        v = str(v)[:2000]
                    elif k == "trim_start":
                        v = clean_trim(v)
                    elif k == "kind":
                        if v not in ("scene", "card"):
                            raise StoryError("A shot is a scene or a card.")
                    elif k == "location":
                        v = " ".join(str(v).split())[:60]
                        if v and p.location(v) is None:
                            raise StoryError(f"There's no stage called {v!r} in this story.")
                        v = p.location(v).name if v else ""
                        if not v:
                            s.stage_angle = ""
                    elif k == "stage_angle":
                        v = " ".join(str(v).split())[:60]
                        loc = p.location(fields.get("location") or s.location)
                        if v and (loc is None or loc.angle(v) is None):
                            raise StoryError(f"That stage has no angle called {v!r}.")
                        v = loc.angle(v).name if v else ""
                    setattr(s, k, v)
            if not s.beat.strip():
                raise StoryError("Give the shot a short title.")
            explicit = "speaker" in dia and bool(dia["speaker"])
            if not explicit and fields.get("characters") is not None:
                _carry_speaker(s, old_cast)
            _speaker_in_cast(s, explicit=explicit)
            if not old_speaker:  # a speaker who left the cast is not replaced by someone else
                _sole_speaker(s)
            return s
        return self._edit(pid, fn)

    def reorder(self, pid: str, order: list[str]) -> Project:
        def fn(p: Project):
            ids = [s.id for s in p.shots]
            if sorted(order) != sorted(ids) or len(set(order)) != len(order):
                raise StoryError("The new order must list every shot exactly once.")
            by = {s.id: s for s in p.shots}
            p.shots = [by[i] for i in order]
        return self._edit(pid, fn)

    def move_shot(self, pid: str, sid: str, delta: int) -> Project:
        def fn(p: Project):
            i = [s.id for s in p.shots].index(p.shot(sid).id)
            j = max(0, min(len(p.shots) - 1, i + int(delta)))
            p.shots.insert(j, p.shots.pop(i))
        return self._edit(pid, fn)

    def delete_shot(self, pid: str, sid: str, confirm: bool = False) -> Project:
        if not confirm:
            raise StoryError("Confirm that you want to delete the shot.")

        def fn(p: Project):
            s = p.shot(sid)
            p.shots.remove(s)
            p.deleted_shots.append(s)  # takes stay on disk and in the file
        return self._edit(pid, fn)

    def restore_shot(self, pid: str, sid: str, index: int | None = None) -> Project:
        """Undo a delete: the shot comes back with every take, at ``index`` (default: the end)."""
        def fn(p: Project):
            s = next((x for x in reversed(p.deleted_shots) if x.id == sid), None)
            if s is None:
                raise NotFound("That shot can't be brought back.")
            p.deleted_shots.remove(s)
            j = len(p.shots) if index is None else max(0, min(len(p.shots), int(index)))
            p.shots.insert(j, s)
        return self._edit(pid, fn)

    def add_shots(self, pid: str, shots: list[dict]) -> Project:
        """Append several shots at once (from a template or a script). All or nothing."""
        rows = check_shots(shots)

        def fn(p: Project):
            for r in rows:  # like add_shot: no cast given (None) casts the story's lead; [] means nobody
                if r.characters is None:
                    r.characters = [p.character] if p.character else []
                    _speaker_in_cast(r, explicit=True)
            p.shots.extend(rows)
        return self._edit(pid, fn)

    # ------------------------------------------------------------ locations
    def set_location(self, pid: str, name: str, image: str | None = None, description: str | None = None,
                     empty: str | None = None, checklist: list[str] | None = None, sheet: str | None = None) -> Location:
        """Add or update a location (stage) of the story: master plate, empty plate, set description, checklist."""
        name = " ".join(str(name or "").split())[:60]
        if not name:
            raise StoryError("Give the stage a name.")

        def fn(p: Project):
            loc = p.location(name)
            if loc is None:
                loc = Location(name=name)
                p.locations.append(loc)
            if image is not None:
                loc.image = str(image)
            if description is not None:
                loc.description = str(description)[:1500]
            if empty is not None:
                loc.empty = str(empty)
            if checklist is not None:
                loc.checklist = [" ".join(str(x).split())[:200] for x in checklist if str(x).strip()][:20]
            if sheet is not None:
                loc.sheet = str(sheet)
            return loc
        return self._edit(pid, fn)

    MAX_ANGLES = 6

    def set_stage_angle(self, pid: str, loc_name: str, angle: str, image: str | None = None,
                        note: str | None = None, status: str | None = None, error: str | None = None) -> StageAngle:
        """Add or update one angle of a stage sheet."""
        angle = " ".join(str(angle or "").split())[:60]
        if not angle:
            raise StoryError("Give the angle a name, e.g. \"behind the counter\".")

        def fn(p: Project):
            loc = p.location(loc_name)
            if loc is None:
                raise NotFound("That location isn't in this story.")
            a = loc.angle(angle)
            if a is None:
                if len(loc.angles) >= self.MAX_ANGLES:
                    raise StoryError(f"A stage sheet holds up to {self.MAX_ANGLES} angles.")
                a = StageAngle(name=angle)
                loc.angles.append(a)
            if image is not None:
                a.image = str(image)
            if note is not None:
                a.note = str(note)[:500]
            if status is not None:
                a.status = status if status in ("", "rendering", "failed") else ""
            if error is not None:
                a.error = str(error)[:300]
            return a
        return self._edit(pid, fn)

    def rename_stage_angle(self, pid: str, loc_name: str, angle: str, new: str) -> StageAngle:
        """Rename an angle; shots that picked it follow the new name."""
        new = " ".join(str(new or "").split())[:60]
        if not new:
            raise StoryError("Give the angle a name, e.g. \"behind the counter\".")

        def fn(p: Project):
            loc = p.location(loc_name)
            a = loc.angle(angle) if loc else None
            if a is None:
                raise NotFound("That angle isn't on this stage sheet.")
            other = loc.angle(new)
            if other is not None and other is not a:
                raise StoryError(f"This stage already has an angle called {other.name!r}.")
            old = a.name
            a.name = new
            for s in p.shots:
                if s.location.lower() == loc.name.lower() and s.stage_angle.lower() == old.lower():
                    s.stage_angle = new
            return a
        return self._edit(pid, fn)

    def remove_stage_angle(self, pid: str, loc_name: str, angle: str) -> Project:
        def fn(p: Project):
            loc = p.location(loc_name)
            a = loc.angle(angle) if loc else None
            if a is None:
                raise NotFound("That angle isn't on this stage sheet.")
            loc.angles.remove(a)
            for s in p.shots:
                if s.location.lower() == loc.name.lower() and s.stage_angle.lower() == a.name.lower():
                    s.stage_angle = ""
        return self._edit(pid, fn)

    def remove_location(self, pid: str, name: str) -> Project:
        """Drop a location; shots set there keep their takes and just lose the link."""
        def fn(p: Project):
            loc = p.location(name)
            if loc is None:
                raise NotFound("That location isn't in this story.")
            p.locations.remove(loc)
            for s in p.shots:
                if s.location.lower() == loc.name.lower():
                    s.location = ""
                    s.stage_angle = ""
        return self._edit(pid, fn)

    # ------------------------------------------------------------ versions
    def take_dir(self, pid: str, sid: str, take: int) -> Path:
        return self.project_dir(pid) / "shots" / sid / f"v{take}"

    def reserve_take(self, pid: str, sid: str) -> int:
        """Claim the next take number for a shot (never reused, even after a delete)."""
        def fn(p: Project):
            s = p.shot(sid)
            n = max([s.next_take, *[v.take + 1 for v in s.versions]])
            s.next_take = n + 1
            return n
        return self._edit(pid, fn)

    def add_version(self, pid: str, sid: str, take: int | None = None, keep: bool = False, **fields) -> Version:
        """Append a new take. Never replaces an existing one."""
        if take is None:
            take = self.reserve_take(pid, sid)

        def fn(p: Project):
            s = p.shot(sid)
            vid = f"v{take}"
            if any(v.id == vid for v in s.versions):
                raise StoryError(f"Take {vid} already exists; OpenSoul never overwrites takes.")
            s.next_take = max(s.next_take, take + 1)
            v = Version(id=vid, take=take, take_id=f"{sid}-{vid}", **fields)
            s.versions.append(v)
            if keep or s.keeper is None and v.status == "ready":
                s.keeper = v.id
            return v
        return self._edit(pid, fn)

    def update_version(self, pid: str, sid: str, vid: str, **fields) -> Version:
        """Fill in a take that was still rendering (status, file, scores). Not for replacing media of a ready take."""
        def fn(p: Project):
            s = p.shot(sid)
            v = s.version(vid)
            if v.status == "ready" and fields.get("file") and fields["file"] != v.file:
                raise StoryError("OpenSoul never overwrites a finished take. Make a new take instead.")
            for k, val in fields.items():
                if hasattr(v, k) and k not in {"id", "take", "take_id"}:
                    setattr(v, k, val)
            if s.keeper is None and v.status == "ready":
                s.keeper = v.id
            return v
        return self._edit(pid, fn)

    def set_keeper(self, pid: str, sid: str, vid: str) -> Shot:
        def fn(p: Project):
            s = p.shot(sid)
            v = s.version(vid)
            if v.status != "ready":
                raise StoryError("That take isn't finished yet.")
            s.keeper = v.id
            return s
        return self._edit(pid, fn)

    def delete_version(self, pid: str, sid: str, vid: str, confirm: bool = False) -> Shot:
        """The only way a take is ever removed: an explicit, confirmed delete by the user."""
        if not confirm:
            raise StoryError("Confirm that you want to delete the take.")

        def fn(p: Project):
            s = p.shot(sid)
            v = s.version(vid)
            s.versions.remove(v)
            if s.keeper == vid:
                ready = [x for x in s.versions if x.status == "ready"]
                s.keeper = ready[-1].id if ready else None
            d = self.take_dir(pid, sid, v.take)
            if d.is_dir():  # only media this project made itself (never repo assets)
                import shutil

                shutil.rmtree(d, ignore_errors=True)
            return s
        return self._edit(pid, fn)


# ---------------------------------------------------------------- export
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv"}


ROOM_TONE_AMP = 0.08  # OS-072: brown-noise room tone under talking takes (about -40 LUFS: heard as air, not hiss)
STILL_SECONDS = 3.0  # a still keeper (or a shot with no Length) with nothing else to go on


def export_plan(p: Project) -> dict:
    """Keepers in shot order. Shots without a keeper are listed as skipped (never silently dropped).

    OS-061: every item carries the shot's planned Length (``seconds``, 0 = the whole take; a still uses 3 s) and its
    start in the keeper (``trim_start``), so the export cuts each shot to its plan."""
    items, skipped = [], []
    for i, s in enumerate(p.shots, 1):
        v = s.keeper_version()
        if v is None or not (v.file or v.poster):
            skipped.append({"index": i, "shot_id": s.id, "beat": s.beat, "reason": "no keeper take yet",
                            "seconds": float(s.seconds or 0)})
            continue
        src = v.file or v.poster
        from opensoul.export_guard import blocked

        if blocked(src):  # concept images never go into an export (opensoul/export_guard.py)
            skipped.append({"index": i, "shot_id": s.id, "beat": s.beat, "reason": "concept image, not exported"})
            continue
        kind = "video" if Path(src).suffix.lower() in VIDEO_EXT else "still"
        items.append({"index": i, "shot_id": s.id, "beat": s.beat, "take": v.id, "take_id": v.take_id,
                      "source": src, "source_kind": kind, "placeholder": v.placeholder, "label": v.label,
                      "seconds": float(s.seconds or 0), "trim_start": float(getattr(s, "trim_start", 0) or 0),
                      "talking": bool(s.line)})
    return {"project": p.id, "title": p.title, "aspect": p.aspect, "items": items, "skipped": skipped,
            "placeholder": any(it["placeholder"] for it in items)}


GAP_REASON = "no keeper take yet"


def fill_gaps(plan: dict) -> dict:
    """OS-065: a shot with no keeper becomes black of its Length (3 s when it has none), so the cut keeps its beat.
    Each one stays listed in ``filled`` (shot, beat, seconds). Other skips (concept images, demo previews) stay skipped."""
    gaps = [x for x in plan["skipped"] if x.get("reason") == GAP_REASON]
    if not gaps:
        plan["filled"] = []
        return plan
    plan["skipped"] = [x for x in plan["skipped"] if x.get("reason") != GAP_REASON]
    for x in gaps:
        secs = float(x.get("seconds") or 0) or STILL_SECONDS
        plan["items"].append({"index": x["index"], "shot_id": x["shot_id"], "beat": x["beat"], "take": None,
                              "take_id": None, "source": None, "source_kind": "black", "placeholder": False,
                              "label": "Black (no keeper yet)", "seconds": secs, "trim_start": 0.0, "talking": False})
    plan["items"].sort(key=lambda it: it["index"])
    plan["filled"] = [{"index": x["index"], "shot_id": x["shot_id"], "beat": x["beat"],
                       "seconds": float(x.get("seconds") or 0) or STILL_SECONDS} for x in gaps]
    return plan


def cut_seconds(it: dict, take_seconds: float | None = None, still_seconds: float = STILL_SECONDS) -> float:
    """How long a shot runs in the export: its Length when set, else what is left of the take after the start
    (a still: 3 s). ``take_seconds`` is the keeper's own length (None = not known)."""
    want = float(it.get("seconds") or 0)
    if want > 0:
        return round(want, 2)
    if it.get("source_kind") != "video":
        return still_seconds
    if not take_seconds:
        return 0.0
    return round(max(0.0, float(take_seconds) - float(it.get("trim_start") or 0)), 2)


def _size(aspect: str) -> tuple[int, int]:
    return (720, 1280) if aspect == "9:16" else (1280, 720)


def _has_audio(src: Path) -> bool:
    import subprocess

    from opensoul.media import ffmpeg_bin

    r = subprocess.run([ffmpeg_bin() or "ffmpeg", "-hide_banner", "-i", str(src)], capture_output=True, text=True)
    return "Audio:" in r.stderr


def render_export(plan: dict, work: Path, still_seconds: float = STILL_SECONDS) -> Path:
    """Normalize each keeper (same size, 24 fps, stereo audio; stills become short clips) and concat them in order.

    OS-061: a shot with a Length is cut to it (from its start in the keeper); a take shorter than its Length holds its
    last frame. A still runs its Length (else 3 s)."""
    from opensoul import media

    w, h = _size(plan.get("aspect", "16:9"))
    work.mkdir(parents=True, exist_ok=True)
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,format=yuv420p"
    segs: list[Path] = []
    for k, it in enumerate(plan["items"], 1):
        seg = work / f"seg_{k:02d}.mp4"
        if it["source_kind"] == "black":  # OS-065: a shot with no keeper keeps its place in the cut
            secs = float(it.get("seconds") or still_seconds)
            media._run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r=24:d={secs}",
                        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{secs}", "-vf", "format=yuv420p",
                        "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(seg)], seg)
            segs.append(seg)
            it["segment"] = str(seg)
            it["cut_seconds"] = round(media.duration(seg), 2)
            continue
        src = abs_path(it["source"])
        from opensoul.export_guard import blocked

        if blocked(it["source"]) or blocked(src):
            raise StoryError(f"Shot {it['index']} ({it['beat']}): OpenSoul cannot export a concept image.")
        if src is None or not src.is_file():
            raise StoryError(f"Shot {it['index']} ({it['beat']}): the keeper file is missing.")
        want = float(it.get("seconds") or 0)
        start = float(it.get("trim_start") or 0) if it["source_kind"] == "video" else 0.0
        cmd = ["ffmpeg", "-y", "-loglevel", "error"]
        if it["source_kind"] == "still":
            cmd += ["-loop", "1", "-t", f"{want or still_seconds}", "-i", str(src)]
        else:
            cmd += (["-ss", f"{start}"] if start > 0 else []) + ["-i", str(src)]
        audio = it["source_kind"] == "video" and _has_audio(src)
        tone = bool(it.get("talking"))  # OS-072: a talking take has only the voice; room tone fills its silence
        if not audio:
            cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        if tone:
            cmd += ["-f", "lavfi", "-i", f"anoisesrc=color=brown:amplitude={ROOM_TONE_AMP}:r=48000"]
        v = vf + (f",tpad=stop_mode=clone:stop_duration={want}" if want > 0 else "")
        a_in = "0:a:0" if audio else "1:a:0"
        if tone:
            pad = ",apad" if want > 0 else ""
            cmd += ["-filter_complex", f"[{a_in}]aformat=sample_rates=48000:channel_layouts=stereo{pad}[a0];"
                    f"[{2 if not audio else 1}:a]lowpass=f=500,highpass=f=40,aformat=sample_rates=48000:channel_layouts=stereo[n];"
                    "[a0][n]amix=inputs=2:duration=first:normalize=0[aout]",
                    "-map", "0:v:0", "-map", "[aout]", "-vf", v]
        else:
            cmd += ["-map", "0:v:0", "-map", a_in, "-vf", v]
        if want > 0:
            cmd += (["-af", "apad"] if audio and not tone else []) + ["-t", f"{want}"]
        else:
            cmd += ["-shortest"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(seg)]
        media._run(cmd, seg)
        segs.append(seg)
        it["segment"] = str(seg)
        it["cut_seconds"] = round(media.duration(seg), 2)
    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{s.name}'\n" for s in segs), encoding="utf-8")
    out = work / f"{slug(plan['title'], 'story')}{'_preview' if plan.get('placeholder') else ''}.mp4"
    media._run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                "-movflags", "+faststart", str(out)], out)
    return out


# ---------------------------------------------------------------- demo project
DEMO_ID = "lumi-night-shift"
DEMO_TITLE = "Lumi – Night Shift"
CONCEPTS = "assets/lumi/concepts"
CONCEPT_LABEL = "Concept image · placeholder"

DEMO_BEATS: list[dict] = [
    {"beat": "Cold open", "camera": "dolly_in",
     "prompt": "3 AM, rain on the convenience-store window. Lumi, bored at the register, reads an ancient book; a ginger cat sleeps on the counter.",
     "concepts": [("v3_cold_open.jpg", "Start frame (photoreal v3 look): Lumi at the register with her ancient book and the cat.")]},
    {"beat": "Doors chime", "camera": "static", "characters": ["Lumi", "Mio", "Ren"],
     "prompt": "The door chimes. Mio and Ren, a tipsy young couple, stumble in out of the rain, laughing.", "concepts": []},
    {"beat": "Canned coffee", "camera": "static", "characters": ["Lumi", "Mio", "Ren"],
     "prompt": "Ren grabs a canned coffee from the fridge and sets it on the counter; Lumi judges him silently.",
     "concepts": []},
    {"beat": "Real coffee", "camera": "dolly_in",
     "prompt": "Lumi takes the can away and makes them real coffee with whole milk, slowly and seriously.",
     "concepts": [("v3_real_coffee.jpg", "Start frame (photoreal v3 look): Lumi pouring hot water over a real coffee.")]},
    {"beat": "Sip and freeze", "camera": "static", "characters": ["Lumi", "Mio", "Ren"],
     "prompt": "Mio and Ren sip. They freeze. Lumi, deadpan, holds her own cup.",
     "concepts": []},
    {"beat": "Into the rain", "camera": "dolly_out", "characters": ["Lumi", "Mio", "Ren"],
     "prompt": "Mio and Ren leave and wave back at her as they step into the rain.", "concepts": []},
    {"beat": "Daydream", "camera": "orbit", "characters": ["Lumi", "Mio", "Ren"],
     "prompt": "Daydream: the three of them on a fantasy adventure, painterly anime style.",
     "concepts": []},
    {"beat": "Ending", "camera": "dolly_in",
     "prompt": ("After they leave, she opens her ancient book: it holds fun moments she remembers, each drawn "
                "anime-style as a fantasy adventure (a fishing trip drawn as a dragon hunt, a 1980s arcade night "
                "drawn as a dungeon raid). She draws tonight's tipsy coffee run with the couple as a new quest, "
                "closes the book softly, and the cat looks at the camera."),
     "concepts": [("v3_ending.jpg", "Start frame (photoreal v3 look): Lumi drawing in her doodle book, the cat beside her.")]},
]


def seed_demo(store: Store, character: str = "Lumi") -> Project | None:
    """Create the 'Lumi – Night Shift' story once (no-op if it already exists, so user edits are kept)."""
    if store.exists(DEMO_ID):
        return None
    with _LOCK:
        p = store.create_project(DEMO_TITLE, character, pid=DEMO_ID)
        return _fill_lumi(store, p, character)


def _fill_lumi(store: Store, p: Project, character: str = "Lumi") -> Project:
    """The demo's eight beats (and its labelled concept stills) into an empty story."""
    with _LOCK:
        for b in DEMO_BEATS:
            s = store.add_shot(p.id, b["beat"], b["prompt"], b.get("characters") or [character], b["camera"])
            for fname, note in b["concepts"]:
                f = f"{CONCEPTS}/{fname}"
                if not (ROOT / f).is_file():
                    continue
                store.add_version(p.id, s.id, file=f, poster=f, prompt=b["prompt"], kind="concept",
                                  placeholder=True, label=CONCEPT_LABEL, note=note,
                                  settings={"source": "concept art (assets/lumi/concepts)"})
        # The milk pour is the keeper for "Real coffee" (whole milk is the point of the beat).
        p = store.load(p.id)
        real = p.shots[3]
        if len(real.versions) > 1:
            store.set_keeper(p.id, real.id, real.versions[-1].id)
        return store.load(p.id)


# OS-001: the Preview demo. Preview takes are sample clips of Juno Pell in 'Spin Cycle' (presets/preview_samples.json),
# so the Preview demo story is that story: shot N's first take is sample clip N, and the words match the pictures.
PREVIEW_DEMO_ID = "juno-spin-cycle"
PREVIEW_DEMO_TITLE = "Juno – Spin Cycle"
PREVIEW_DEMO_CAST = "Juno Pell"
PREVIEW_DEMO_BEATS = [
    {"beat": "Laundromat, 2 a.m.", "camera": "static",
     "prompt": "2 a.m. in an empty laundromat. Juno folds a warm towel at the folding table. Wide shot."},
    {"beat": "The disco turns on", "camera": "dolly_out",
     "prompt": "The lights change color and the laundromat turns into a disco. Juno dances between the washers. Wide shot."},
    {"beat": "Tangerine close-up", "camera": "push_in_gentle",
     "prompt": "Juno, in a tangerine suit, sings under the disco lights. Close-up."},
    {"beat": "The lost sock", "camera": "static",
     "prompt": "Juno sings and holds up one lost sock that she found in a dryer. Medium shot."},
    {"beat": "Washer wall", "camera": "dolly_left",
     "prompt": "Juno, in the tangerine suit, stands by the wall of glowing washers. Wide shot."},
]


def seed_preview_demo(store: Store) -> Project | None:
    """Create 'Juno – Spin Cycle' once, in Preview mode (no-op if it exists, so user edits are kept)."""
    if store.exists(PREVIEW_DEMO_ID):
        return None
    with _LOCK:
        p = store.create_project(PREVIEW_DEMO_TITLE, PREVIEW_DEMO_CAST, pid=PREVIEW_DEMO_ID, aspect="9:16")
        for b in PREVIEW_DEMO_BEATS:
            store.add_shot(p.id, b["beat"], b["prompt"], [PREVIEW_DEMO_CAST], b["camera"])
        return store.load(p.id)


OLD_DEMO_CAST = "Young couple (extras)"


def _stale_concept(v: Version) -> bool:
    """A demo placeholder from before the photoreal v3 look (the rejected v2 art)."""
    return (v.kind == "concept" and v.placeholder and str(v.file).startswith(CONCEPTS + "/")
            and not Path(str(v.file)).name.startswith("v3_"))


def refresh_demo(store: Store) -> bool:
    """Bring an older 'Lumi – Night Shift' up to the current demo: Mio and Ren instead of the unnamed
    couple, and no placeholder stills in the rejected v2 look. Real takes and user edits are never touched.
    Returns True when something changed."""
    if not store.exists(DEMO_ID):
        return False
    beats = {b["beat"]: b for b in DEMO_BEATS}

    def fn(p: Project):
        changed = False
        for s in p.shots:
            b = beats.get(s.beat)
            if not b:
                continue
            if OLD_DEMO_CAST in s.characters and b.get("characters"):
                s.characters = list(b["characters"])
                s.prompt = b["prompt"]
                changed = True
            stale = [v for v in s.versions if _stale_concept(v)]
            if stale:
                s.versions = [v for v in s.versions if not _stale_concept(v)]
                changed = True
                if s.keeper and s.keeper not in {v.id for v in s.versions}:
                    s.keeper = s.versions[-1].id if s.versions else None
            have = {Path(str(v.file)).name for v in s.versions}
            for fname, note in b["concepts"]:
                f = f"{CONCEPTS}/{fname}"
                if fname in have or not (ROOT / f).is_file():
                    continue
                take = s.next_take
                s.next_take += 1
                v = Version(id=f"v{take}", take=take, take_id=f"{s.id}-v{take}", file=f, poster=f, prompt=b["prompt"],
                            kind="concept", placeholder=True, label=CONCEPT_LABEL, note=note,
                            settings={"source": "concept art (assets/lumi/concepts)"})
                s.versions.append(v)
                s.keeper = s.keeper or v.id
                changed = True
        return changed
    with _LOCK:  # save only when something changed, so a server restart never rewrites the demo file
        p = store.load(DEMO_ID)
        if not fn(p):
            return False
        store.save(p)
        return True


# ---------------------------------------------------------------- templates (New story → Start from a template)
TEMPLATES_DIR = ROOT / "presets" / "story_templates"
LUMI_TEMPLATE = "lumi-night-shift"


def list_templates() -> list[dict]:
    """Blank first, then the Lumi demo, then every presets/story_templates/*.json (sorted by ``order``)."""
    out = [{"id": "blank", "title": "Blank", "blurb": "Start with no shots and add your own.", "shots": [], "order": 0},
           {"id": LUMI_TEMPLATE, "title": DEMO_TITLE, "order": 10,
            "blurb": "The demo: a night-shift barista, a tipsy couple and real coffee. Eight shots, Lumi, Mio and Ren.",
            "shots": [{"beat": b["beat"], "camera": b["camera"], "prompt": b["prompt"],
                       "characters": b.get("characters") or ["Lumi"]} for b in DEMO_BEATS]}]
    if TEMPLATES_DIR.is_dir():
        for f in sorted(TEMPLATES_DIR.glob("*.json")):
            try:
                t = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if not isinstance(t, dict) or not t.get("id") or t["id"] in {"blank", LUMI_TEMPLATE}:
                continue
            out.append({"id": str(t["id"]), "title": str(t.get("title") or t["id"]), "blurb": str(t.get("blurb") or ""),
                        "order": int(t.get("order") or 50), "shots": list(t.get("shots") or [])})
    out.extend(flagged_templates(skip={t["id"] for t in out}))
    return sorted(out, key=lambda t: (t["order"], t["title"]))


FLAGGED_TEMPLATES_DIR = ROOT / "presets" / "story_templates_flagged"


def flagged_templates(env: dict | None = None, skip: set | None = None) -> list[dict]:
    """Experimental templates (music video, UGC ad, product shots) from presets/story_templates_flagged/. Each names a
    feature flag; it is listed only when that environment variable is "1". All flags are off by default, so the
    template list is unchanged unless you opt in (docs/TEMPLATES.md)."""
    env = os.environ if env is None else env
    out = []
    if not FLAGGED_TEMPLATES_DIR.is_dir():
        return out
    for f in sorted(FLAGGED_TEMPLATES_DIR.glob("*.json")):
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not isinstance(t, dict) or not t.get("id") or not str(t.get("flag") or "").startswith("OPENSOUL_FEATURE_"):
            continue
        if (env.get(t["flag"]) or "").strip() != "1" or t["id"] in (skip or set()) | {"blank", LUMI_TEMPLATE}:
            continue
        out.append({"id": str(t["id"]), "title": str(t.get("title") or t["id"]), "blurb": str(t.get("blurb") or ""),
                    "order": int(t.get("order") or 50), "shots": list(t.get("shots") or []), "experimental": True})
    return out


def template(tid: str) -> dict:
    t = next((x for x in list_templates() if x["id"] == tid), None)
    if t is None:
        raise NotFound("Unknown template.")
    return t


def create_from_template(store: Store, tid: str, title: str = "", lead: str = "", cameras: set[str] | None = None) -> Project:
    """A NEW story from a template. The demo story itself is never touched (a copy gets its own id)."""
    t = template(tid or "blank")
    lead = " ".join(str(lead or "").split())[:60]
    if t["id"] == LUMI_TEMPLATE:
        p = store.create_project(title or DEMO_TITLE, lead or "Lumi", pid=None if title else f"{DEMO_ID}-copy")
        return _fill_lumi(store, p, p.character)
    p = store.create_project(title or (t["title"] if t["id"] != "blank" else "Untitled story"), lead)
    rows = []
    for d in t["shots"]:
        who = lead or "your character"
        cam = str(d.get("camera") or "static")
        rows.append({"beat": d.get("beat") or "Shot", "prompt": str(d.get("prompt") or "").replace("{lead}", who),
                     "characters": d.get("characters") if d.get("characters") is not None else ([lead] if lead else []),
                     "camera": cam if cameras is None or cam in cameras else "static"})
    if rows:
        store.add_shots(p.id, rows)
    return store.load(p.id)
