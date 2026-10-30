"""Concept images (assets/lumi/concepts/ and any other concepts/ folder) never leave the app in an export."""
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from opensoul import export_guard, storyboard as sb
from release_assets import CONCEPT, DEMO_POSTER, requires_demo_asset, requires_git, V8F_TAKE

ROOT = Path(__file__).resolve().parents[1]


@requires_demo_asset(CONCEPT)
def test_every_concept_file_is_blocked_and_listed():
    files = export_guard.concept_files()
    assert ROOT / "assets/lumi/concepts/lumi_real_B.jpg" in files and len(files) >= 9
    for f in files:
        assert export_guard.blocked(f) and export_guard.blocked(f.relative_to(ROOT).as_posix()), f
    assert export_guard.blocked("assets/demo_samples/lumi_video_poster.png")  # a crop of a concept
    assert not export_guard.blocked("assets/demo_audited/placeholder_mio.svg")  # drawn placeholders ship


def test_story_export_skips_concept_keepers(tmp_path):
    st = sb.Store(tmp_path)
    p = st.create_project("T", "Lumi")
    s = st.add_shot(p.id, "One", "x", ["Lumi"], "static")
    st.add_version(p.id, s.id, file="assets/lumi/concepts/v3_cold_open.jpg", poster="assets/lumi/concepts/v3_cold_open.jpg",
                   prompt="x", kind="concept", placeholder=True, label="c", note="", settings={})
    st.set_keeper(p.id, s.id, st.load(p.id).shots[0].versions[0].id)
    plan = sb.export_plan(st.load(p.id))
    assert plan["items"] == [] and plan["skipped"][0]["reason"] == "concept image, not exported"
    bad = {"title": "T", "aspect": "16:9", "items": [{"index": 1, "beat": "One", "source": "assets/lumi/concepts/lumi_real_B.jpg", "source_kind": "still"}]}
    try:
        sb.render_export(bad, tmp_path / "w")
        raise AssertionError("render_export took a concept image")
    except sb.StoryError as e:
        assert "concept image" in str(e)


@requires_demo_asset(DEMO_POSTER)
def test_vertical_clip_refuses_concept_images(monkeypatch, tmp_path):
    import app.server as server
    monkeypatch.setattr(server, "DATA", tmp_path)
    seen = []
    monkeypatch.setattr(server, "_export_vertical", lambda src, dest: seen.append(src) or src is not None)
    TestClient(server.app).post("/api/share", json={"video_url": f"/api/file?path={ROOT}/assets/lumi/concepts/lumi_real_B.jpg"})
    assert seen == [None]
    assert server._poster_url() == "/assets/demo_audited/placeholder_tile.jpg"  # demo preview: a neutral placeholder


GATE_HITS = [  # Contest Submission's hash gate at 69e05a4, outside concepts/
    "assets/lumi/lumi_character_sheet_v3.jpg", "assets/lumi/lumi_character_sheet_v3_trimmed.jpg", "assets/lumi/lumi_ref_v3.jpg",
    "assets/lumi/lumi_ref_v3_full_trim.jpg", "assets/lumi/lumi_ref_v3_trim.jpg", "assets/demo_samples/lumi_still_01_front.png",
    "assets/demo_samples/lumi_pack/refs/ref_00.png", "assets/demo_samples/lumi_pack/refs/ref_01.png",
    "assets/demo_audited/konbini_master.jpg", "assets/demo_audited/shot01_cold_open_v8e_f24.jpg",
    "assets/demo_audited/shot01_cold_open_v8f_f28.jpg"]
CEO_A = ["assets/demo_audited/shot01_doodling_v8f.mp4", "assets/demo_audited/lumi_card_v8f_f18.jpg",
         "assets/demo_audited/tile_still_v8f_f24.jpg"]
CEO_B = ["assets/demo_audited/konbini_window_side.jpg", "assets/demo_audited/konbini_register.jpg",
         "assets/demo_audited/stage_konbini_sheet_v6.jpg", "assets/demo_audited/lumi_talk_l04_s171_f13_c318.jpg",
         "assets/demo_audited/lumi_card_v8e_f24.jpg", "assets/demo_audited/tile_still_v8e_f24.jpg"]
CEO_C = [f"assets/preset_thumbs/camera/{n}.mp4" for n in ("crash_zoom", "dolly_in", "dolly_left", "dolly_out", "dolly_right",
         "dolly_zoom", "fpv", "jib_down", "jib_up", "push_in_gentle", "static")] + [
         f"assets/preset_thumbs/effects/{n}.mp4" for n in ("day_to_night", "earth_zoom_out", "outfit_switch")]


CEO_D = ["assets/demo_samples/lumi_sheet_preview.jpg", "assets/demo_samples/lumi_still_02_side.png",
         "assets/demo_samples/lumi_still_03_close.png", "assets/demo_samples/lumi_pack/refs/ref_02.png"]


def test_every_listed_file_is_blocked_and_nothing_else_in_demo_audited_or_preset_thumbs_ships():
    want = set(GATE_HITS + CEO_A + CEO_B + CEO_C + CEO_D + ["assets/demo_samples/lumi_video_poster.png"])
    assert export_guard.DERIVED == want and len(CEO_C) == 14
    left = {f.relative_to(ROOT).as_posix() for d in ("assets/demo_audited", "assets/preset_thumbs") for f in (ROOT / d).rglob("*")
            if f.is_file() and not export_guard.blocked(f.relative_to(ROOT).as_posix())}
    # only drawn placeholders (SVG, or the plain-gradient placeholder_*.jpg stills) and READMEs ship
    assert all(p.endswith((".svg", ".md")) or p.rsplit("/", 1)[-1].startswith("placeholder_") for p in left), left


@requires_git
@requires_demo_asset()
def test_release_archives_leave_concepts_and_derived_files_out():
    for rel in export_guard.DERIVED:
        assert (ROOT / rel).is_file() and export_guard.blocked(rel), rel  # still in the tree (live UI), never exported
    whole = [f for d in sorted(export_guard.DERIVED_DIRS) for f in sorted((ROOT / d).rglob("*")) if f.is_file()]
    assert whole and all(export_guard.blocked(f.relative_to(ROOT).as_posix()) for f in whole)
    for f in export_guard.concept_files() + [ROOT / p for p in sorted(export_guard.DERIVED | export_guard.PRE_REBUILD)] + whole:
        out = subprocess.run(["git", "check-attr", "export-ignore", "--", f.relative_to(ROOT).as_posix()],
                             cwd=ROOT, capture_output=True, text=True).stdout
        assert out.strip().endswith("export-ignore: set"), out


GATE = Path("/workspace/review/submission/tools")  # Contest Submission's gate (read only; not part of the repo)


def _gate_or_skip():
    import pytest

    need = ["gate_hash_check.py", "gate_hash_deny.txt", "gate_derivative_watch.txt"]
    missing = [n for n in need if not (GATE / n).is_file()]
    if missing:
        pytest.skip(f"Contest Submission's gate isn't on this machine ({GATE}: missing {', '.join(missing)}); "
                    "it only exists on the build box, so a fresh clone skips this check")
    return GATE


def _watch_globs(gate):
    return [l.split("#", 1)[0].strip() for l in (gate / "gate_derivative_watch.txt").read_text().splitlines()
            if l.split("#", 1)[0].strip()]


@requires_git
def test_contest_gate_is_green_on_a_full_release_archive(tmp_path):
    """Full gate run, read-only: sha256 + image dHash + video dHash (3 frames per video) + the derivative watch list,
    on `git archive` of the working tree (export-ignore applied). Slow-ish (up to ~20 s) but runs by default."""
    gate = _gate_or_skip()
    tree = subprocess.run(["git", "stash", "create"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or "HEAD"
    arc = subprocess.run(["git", "archive", "--worktree-attributes", tree], cwd=ROOT, capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(tmp_path)], input=arc, check=True)
    r = subprocess.run(["python3", str(gate / "gate_hash_check.py"), str(gate / "gate_hash_deny.txt"), str(tmp_path), "5",
                        "--watch", str(gate / "gate_derivative_watch.txt"), "--video-frames", "3"],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0 and "SETUP" not in r.stdout, r.stdout + r.stderr
    kinds = ("hash_deny", "hash_near", "hash_near_video", "derivative_pending")
    assert [l for l in r.stdout.splitlines() if l.split(" ", 1)[0] in kinds] == []
    assert any(f.suffix == ".py" for f in tmp_path.rglob("*.py"))  # the archive is a real export, not an empty dir


@requires_git
@requires_demo_asset()
def test_every_watch_list_entry_is_export_ignored_and_blocked():
    import fnmatch

    gate = _gate_or_skip()
    files = [f.relative_to(ROOT).as_posix() for f in ROOT.rglob("*") if f.is_file()
             and not ({".git", ".venv", "node_modules", "data"} & set(f.relative_to(ROOT).parts))]
    hit = sorted({rel for g in _watch_globs(gate) for rel in files if fnmatch.fnmatchcase(rel, g)})
    assert len(hit) >= 23 and "assets/demo_audited/shot01_doodling_v8f.mp4" in hit
    assert "assets/preset_thumbs/effects/day_to_night.mp4" in hit  # today's video near-match, with v8f
    for rel in hit:
        assert export_guard.blocked(rel), rel
        out = subprocess.run(["git", "check-attr", "export-ignore", "--", rel], cwd=ROOT, capture_output=True, text=True).stdout
        assert out.strip().endswith("export-ignore: set"), out


@requires_demo_asset(V8F_TAKE, "assets/preset_thumbs/effects/day_to_night.mp4")
def test_the_gate_video_check_does_see_the_excluded_clips(tmp_path):
    """Control: the same gate call flags the two clips we exclude, so a green run above means 'left out', not 'not checked'."""
    import shutil

    gate = _gate_or_skip()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        import pytest
        pytest.skip("ffmpeg/ffprobe not installed: the gate skips its video check too")
    for rel in ("assets/demo_audited/shot01_doodling_v8f.mp4", "assets/preset_thumbs/effects/day_to_night.mp4"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, tmp_path / rel)
    out = subprocess.run(["python3", str(gate / "gate_hash_check.py"), str(gate / "gate_hash_deny.txt"), str(tmp_path), "5",
                          "--video-frames", "3"], capture_output=True, text=True, timeout=300).stdout
    assert sorted(l.split()[1] for l in out.splitlines() if l.startswith("hash_near_video")) == [
        "assets/demo_audited/shot01_doodling_v8f.mp4", "assets/preset_thumbs/effects/day_to_night.mp4"]


@requires_git
def test_internal_files_never_go_public():
    for rel in sorted(export_guard.NOT_PUBLIC):
        tracked = subprocess.run(["git", "ls-files", "--", rel], cwd=ROOT, capture_output=True, text=True).stdout.split()
        # A public clone has none of these files: then check a path inside the folder (Path() drops a trailing "/").
        for f in tracked or [rel + "probe.md" if rel.endswith("/") else rel]:
            assert export_guard.blocked(f), f
            out = subprocess.run(["git", "check-attr", "export-ignore", "--", f], cwd=ROOT, capture_output=True, text=True).stdout
            assert out.strip().endswith("export-ignore: set"), out


def test_the_demo_lumi_pack_folder_is_left_out_whole():
    d = "assets/demo_samples/lumi_pack/"
    assert d in export_guard.DERIVED_DIRS
    assert export_guard.blocked(d + "pack.json") and export_guard.blocked(d + "refs/ref_00.png")
    assert not export_guard.blocked("assets/demo_samples/pixel_pack/pack.json")  # Pixel (Apache-2.0) still ships
    assert f"{d}** export-ignore" in (ROOT / ".gitattributes").read_text().splitlines()


@requires_git
def test_an_exported_pack_never_points_at_a_file_the_export_leaves_out(tmp_path):
    """Every pack.json in a `git archive` of the working tree only references pictures that are in the archive too
    (a pack whose refs are export-ignored has to be left out whole, see DERIVED_DIRS)."""
    import json

    tree = subprocess.run(["git", "stash", "create"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or "HEAD"
    arc = subprocess.run(["git", "archive", "--worktree-attributes", tree], cwd=ROOT, capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(tmp_path)], input=arc, check=True)
    packs = sorted(tmp_path.rglob("pack.json"))
    assert packs and not [f for f in (tmp_path / "assets/demo_samples/lumi_pack").rglob("*") if f.is_file()]
    for p in packs:
        d = json.loads(p.read_text())
        for r in list(d.get("ref_images") or []) + [d.get("lora_path")]:
            if r:
                f = Path(r) if Path(r).is_absolute() else p.parent / r
                assert f.is_file(), f"{p.relative_to(tmp_path)} points at {r}, which the export leaves out"
                assert not export_guard.blocked(f.relative_to(tmp_path).as_posix()), r


PRE_REBUILD = ["assets/lumi/lumi_character_sheet_v1.jpg", "assets/lumi/lumi_ref_00.jpg", "assets/lumi/lumi_still_01.jpg",
               "assets/mio/mio_character_sheet_v1.jpg", "assets/mio/mio_ref_00.jpg", "assets/ren/ren_character_sheet_v1.jpg",
               "assets/ren/ren_ref_00.jpg", "assets/demo_samples/lumi_still_reject_demo.png", "docs/media/opensoul_demo.gif",
               "docs/media/credits/credits_card.png"]


def test_pre_rebuild_character_art_is_left_out_and_the_readme_does_not_embed_it():
    assert export_guard.PRE_REBUILD == set(PRE_REBUILD)
    assert all(export_guard.blocked(p) for p in PRE_REBUILD)
    lines = (ROOT / ".gitattributes").read_text().splitlines()
    assert all(f"{p} export-ignore" in lines for p in PRE_REBUILD)
    readme = (ROOT / "README.md").read_text()
    assert not any(f"]({p})" in readme or f'src="{p}"' in readme for p in PRE_REBUILD + sorted(export_guard.DERIVED))
