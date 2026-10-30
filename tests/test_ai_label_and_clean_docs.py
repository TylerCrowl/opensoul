"""Shared captions, the credits card, the in-app credits and the README say the videos are AI-generated (the
LTX-2.x Community License asks for AI output to be labelled). Shipped presets and docs carry no machine paths and
no internal team or role names."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AI = "Videos made with OpenSoul are AI-generated."


def test_ai_label_everywhere():
    from opensoul.presets import caption_for

    assert AI in caption_for({"title": "Dolly in"}, "Kai")
    assert AI in (ROOT / "app/web/static/app.js").read_text().split('$("caption").value =')[1].split("\\n")[0]
    card = (ROOT / "scripts/make_credits_card.py").read_text()
    footer = card.split("FOOTER = ")[1].split("\\n")[0]
    assert AI in footer and all(n in footer for n in ("Lumi", "Mio", "Ren", "Pixel"))
    assert AI in (ROOT / "app/web/index.html").read_text() and AI in (ROOT / "README.md").read_text()


BAD = re.compile(r"/workspace/|(?<![A-Za-z_])review/|for_owner/|Content CEO|Shot Auditor|Contest Submission|Model Scout|"
                 r"Lip-sync Specialist|\\bHank\\b")


def _attr_re(pat: str):
    """A .gitattributes path pattern as a regex over repo-relative paths (*, ** and a slash-less basename pattern)."""
    if "/" not in pat.rstrip("/"):
        pat = "**/" + pat
    out, i = "", 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pat.startswith("/**", i):
            out, i = out + "/.*", i + 3
        elif pat[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pat[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pat[i]), i + 1
    return re.compile(out.lstrip("/") + r"\Z")


def _export_ignored(rel):
    """Paths marked export-ignore. Read from .gitattributes itself, so a copy of the repo without .git (or a git that
    refuses this checkout) still leaves them out; `git check-attr` adds anything git resolves on top."""
    attrs = ROOT / ".gitattributes"
    pats = [_attr_re(ln.split()[0]) for ln in (attrs.read_text().splitlines() if attrs.is_file() else [])
            if ln.strip() and not ln.lstrip().startswith("#") and "export-ignore" in ln.split()[1:]]
    ignored = {r for r in rel if any(p.match(r) for p in pats)}
    if (ROOT / ".git").exists():
        out = subprocess.run(["git", "check-attr", "export-ignore", "--", *rel], cwd=ROOT, capture_output=True, text=True).stdout
        ignored |= {line.split(": ")[0] for line in out.splitlines() if line.endswith(": set")}
    return ignored


def _shipped(paths):
    """Files that go into a release archive (export-ignore ones stay out), relative to the repo."""
    files = [p for g in paths for p in ROOT.glob(g) if p.is_file()]
    rel = [p.relative_to(ROOT).as_posix() for p in files]
    ignored = _export_ignored(rel)
    return [p for p, r in zip(files, rel) if r not in ignored]


def test_export_ignore_is_read_without_git():
    rel = ["docs/WIN_CHECKLIST.md", "scripts/box_bootstrap.sh", "docs/drafts/x.md", "notes/a/b.md",
           "assets/lumi/concepts/c.jpg", "docs/MUSIC.md", "scripts/download_models.sh", "README.md"]
    ign = _export_ignored(rel)
    assert {"docs/WIN_CHECKLIST.md", "scripts/box_bootstrap.sh", "docs/drafts/x.md", "notes/a/b.md", "assets/lumi/concepts/c.jpg"} <= ign
    assert not ign & {"docs/MUSIC.md", "scripts/download_models.sh", "README.md"}  # shipped files are still checked


def test_the_check_still_catches_a_shipped_file():
    assert BAD.search("see /workspace/opensoul") and BAD.search("ask the Shot Auditor")
    assert "docs/MUSIC.md" in {p.relative_to(ROOT).as_posix() for p in _shipped(["docs/*.md"])}


def test_no_internal_paths_or_role_names_in_shipped_presets_and_docs():
    hits = []
    for p in _shipped(["presets/**/*.json", "docs/**/*.md", "assets/**/README.md", "assets/**/*.json", "*.md"]):
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if BAD.search(line):
                hits.append(f"{p.relative_to(ROOT)}:{i}")
    assert not hits, hits


CODE = ["app/**/*.py", "app/web/**/*.html", "app/web/**/*.js", "app/web/**/*.css", "opensoul/**/*.py", "scripts/**/*.py",
        "scripts/**/*.sh", "custom_nodes/**/*.py", "workflows/**/*.json", "*.sh", "Makefile"]


def test_no_internal_paths_or_role_names_in_shipped_code():
    hits = []
    for p in _shipped(CODE):
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if BAD.search(line):
                hits.append(f"{p.relative_to(ROOT)}:{i}")
    assert not hits, hits


def test_no_anime_wording_in_the_demo_script():
    p = ROOT / "docs/stories/lumi_night_shift_script.md"
    if p.is_file():
        s = p.read_text(encoding="utf-8")
        assert "Why it reads as the anime" not in s and "composed mage girl" not in s


def test_no_anime_couple_nod():
    for rel in ("assets/mio/README.md", "assets/ren/README.md", "presets/character_origin.json",
                "assets/mio/character.json", "assets/ren/character.json"):
        assert "well-loved anime couple" not in (ROOT / rel).read_text(), rel


def test_submission_draft_is_a_pointer():
    p = ROOT / "docs/drafts/SUBMISSION.md"
    if not p.is_file():
        return  # docs/drafts stays out of release archives
    s = p.read_text()
    assert "private" in s and len(s) < 600 and "/" not in s.replace("../../README.md", "")
