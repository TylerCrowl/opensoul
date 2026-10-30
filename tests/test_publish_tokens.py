"""P0-02: the README's missing links read honestly and carry one marked token each; the checklist lists every token."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_publish_tokens as C  # noqa: E402


def test_no_old_style_placeholders_left():
    assert "OLD_PLACEHOLDER" not in C.scan(), C.scan().get("OLD_PLACEHOLDER")


def test_checklist_lists_exactly_the_tokens_in_the_repo():
    listed = set(re.findall(r"`PUBLISH-TODO:([A-Z0-9_]+)`", (ROOT / "docs/PUBLISH_CHECKLIST.md").read_text())) - {"NAME"}
    assert listed == set(C.scan()), (listed, set(C.scan()))


def test_readme_reads_cleanly():
    readme = (ROOT / "README.md").read_text()
    shown = re.sub(r"<!--.*?-->", "", readme, flags=re.S)
    assert "PUBLISH-TODO" not in shown  # tokens hide in comments
    assert "coming with the first release" in shown and "[DEMO_VIDEO_LINK]" not in readme and "<ver>" not in readme


def test_strict_mode_fails_while_tokens_remain():
    assert C.main(["--strict"]) == (1 if C.scan() else 0)
