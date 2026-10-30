"""Every Hugging Face repo that scripts/download_models.sh fetches must have a row in the README license table.

Keeps the Open Weights Only disclosure (README, demo credits, Typeform) in sync with what a fresh clone downloads.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = re.compile(r"\$HF/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/resolve/")


def downloader_repos() -> set[str]:
    return set(REPO.findall((ROOT / "scripts" / "download_models.sh").read_text()))


def license_section() -> str:
    readme = (ROOT / "README.md").read_text()
    start = readme.index("### Licenses")
    end = readme.index("\n#", start + 1)
    return readme[start:end]


def test_downloader_has_repos():
    assert len(downloader_repos()) >= 5


def test_every_downloaded_repo_has_a_license_row():
    table = license_section()
    missing = sorted(r for r in downloader_repos() if f"huggingface.co/{r}" not in table)
    assert not missing, f"add a README license row for: {missing}"
