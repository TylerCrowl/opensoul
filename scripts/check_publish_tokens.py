"""List the PUBLISH-TODO tokens that must be filled in before OpenSoul goes public (docs/PUBLISH_CHECKLIST.md).

    python scripts/check_publish_tokens.py            # lists them; exit 0
    python scripts/check_publish_tokens.py --strict   # exit 1 while any token is left (run this before publishing)

A token is the text PUBLISH-TODO:NAME (NAME in capitals), usually inside an HTML comment so the page reads cleanly.
It also flags the old placeholder forms ([REPO_URL], [DEMO_VIDEO_LINK], [RELEASES_URL], <ver> in README.md)."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKEN = re.compile(r"PUBLISH-TODO:([A-Z][A-Z0-9_]+)")
OLD = re.compile(r"\[(?:REPO_URL|RELEASES_URL|[A-Z_]+_LINK)[^\]]*\]")
SKIP = ("docs/PUBLISH_CHECKLIST.md", "scripts/check_publish_tokens.py", "tests/", "notes/", "docs/drafts/",
        "docs/WIN_CHECKLIST.md", "docs/OWNER_ASKS.md")
TEXT = (".md", ".txt", ".html", ".js", ".py", ".json", ".yml", ".yaml", ".sh", ".ps1", ".plist")


def files() -> list[Path]:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, check=True).stdout
        names = out.splitlines()
    except (OSError, subprocess.CalledProcessError):  # a release archive has no .git
        names = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [ROOT / n for n in names if n.endswith(TEXT) and not n.startswith(SKIP)]


def scan() -> dict[str, list[str]]:
    """{token name: ["file:line", ...]}; old-style placeholders are listed under OLD_PLACEHOLDER."""
    hits: dict[str, list[str]] = {}
    for f in files():
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        rel = f.relative_to(ROOT).as_posix()
        for i, line in enumerate(lines, 1):
            for m in TOKEN.finditer(line):
                hits.setdefault(m.group(1), []).append(f"{rel}:{i}")
            if OLD.search(line) or (rel == "README.md" and "<ver>" in line):
                hits.setdefault("OLD_PLACEHOLDER", []).append(f"{rel}:{i}")
    return hits


def main(argv: list[str]) -> int:
    hits = scan()
    for name in sorted(hits):
        print(f"{name}: {', '.join(hits[name])}")
    if not hits:
        print("No PUBLISH-TODO tokens left.")
    return 1 if hits and "--strict" in argv else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
