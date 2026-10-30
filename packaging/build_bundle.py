#!/usr/bin/env python3
"""Build a one-click OpenSoul desktop package: a private Python, the pinned wheels and the app, in one archive.

    python packaging/build_bundle.py --target mac-arm64      # dist/OpenSoul-<ver>-mac-arm64.zip  (OpenSoul.app)
    python packaging/build_bundle.py --target mac-x64        # Intel Macs
    python packaging/build_bundle.py --target linux-x64      # dist/OpenSoul-<ver>-linux-x64.tar.gz
    python packaging/build_bundle.py --target linux-arm64    # DGX Spark / other arm64 Linux
    python packaging/build_bundle.py --target windows-x64    # dist/OpenSoul-<ver>-windows-x64.zip

Runs on any OS with Python 3.10+ and pip (cross-builds: the wheels are fetched for the target platform). Needs the
internet once to fetch python-build-standalone and the wheels; both are cached under ~/.cache/opensoul-build and the
Python archive is checked against the release's SHA256SUMS. The app itself comes from ``git archive <ref>``, so a
package only ever contains committed, public files (never data/, local renders or untracked files).

No signing here: macOS and Windows show a one-time "unidentified developer" prompt; docs/DESKTOP.md explains it.

macOS: OpenSoul.app opens in its own window (pywebview + WKWebView, requirements-desktop-mac.txt) with the OpenSoul
icon (packaging/icon/OpenSoul-1024.png, drawn from app/web/static/opensoul-icon.svg) in the Dock, Launchpad and
Applications. A drag-to-Applications .dmg needs macOS's hdiutil: the desktop CI workflow's macOS job builds it with
``python packaging/make_dmg.py`` (dmgbuild); this script only writes the .zip.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
PBS_RELEASE = "20261021"
PY_VERSION = "3.12.15"
PY_SHORT = "3.12"
PBS_BASE = f"https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_RELEASE}"
PROXY_TOOLS_SDIST = "https://files.pythonhosted.org/packages/source/p/proxy_tools/proxy_tools-0.1.0.tar.gz"
PROXY_TOOLS_SDIST_SHA256 = "ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010"
ICON_MASTER = HERE / "icon" / "OpenSoul-1024.png"
BUNDLE_ID = "org.opensoul.app"

TARGETS = {
    "mac-arm64": {"triple": "aarch64-apple-darwin", "os": "mac", "arch": "arm64",
                  "platforms": [f"macosx_{v}_arm64" for v in ("11_0", "12_0", "13_0", "14_0")]
                  + [f"macosx_{v}_universal2" for v in ("10_9", "10_13", "11_0", "12_0", "13_0")],
                  "extra_requirements": "requirements-desktop-mac.txt"},
    "mac-x64": {"triple": "x86_64-apple-darwin", "os": "mac", "arch": "x86_64",
                "platforms": [f"macosx_{v}_x86_64" for v in ("10_9", "10_12", "10_13", "10_15", "11_0", "12_0", "13_0")]
                + [f"macosx_{v}_universal2" for v in ("10_9", "10_13", "11_0", "12_0")],
                "extra_requirements": "requirements-desktop-mac.txt",
                # newer OpenCV wheels for Intel Macs need macOS 14+; 4.12 still runs on 13 (and wants numpy < 2.3)
                "pins": {"opencv-python-headless": "4.12.0.88", "numpy": "2.2.6"}},
    "linux-x64": {"triple": "x86_64-unknown-linux-gnu", "os": "linux", "arch": "x86_64",
                  "platforms": ["manylinux_2_17_x86_64", "manylinux2014_x86_64", "manylinux_2_28_x86_64", "linux_x86_64"]},
    "linux-arm64": {"triple": "aarch64-unknown-linux-gnu", "os": "linux", "arch": "aarch64",
                    "platforms": ["manylinux_2_17_aarch64", "manylinux2014_aarch64", "manylinux_2_28_aarch64"]},
    "windows-x64": {"triple": "x86_64-pc-windows-msvc", "os": "windows", "arch": "AMD64", "platforms": ["win_amd64"]},
}
# Repo folders a desktop user never needs (they stay in the source repo).
EXCLUDE_TOP = ("tests/", "notes/", "docs/evidence/", "docs/drafts/", "tools/", "cvenv/", ".github/")


def log(msg: str) -> None:
    print(f"[bundle] {msg}", flush=True)


def cache_dir() -> Path:
    d = Path(os.environ.get("OPENSOUL_BUILD_CACHE", Path.home() / ".cache" / "opensoul-build"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch(url: str, dest: Path) -> Path:
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    log(f"downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    os.replace(tmp, dest)
    return dest


def python_archive(triple: str) -> Path:
    name = f"cpython-{PY_VERSION}+{PBS_RELEASE}-{triple}-install_only.tar.gz"
    sums = fetch(f"{PBS_BASE}/SHA256SUMS", cache_dir() / f"SHA256SUMS-{PBS_RELEASE}")
    want = next((ln.split()[0] for ln in sums.read_text().splitlines() if ln.strip().endswith(name)), None)
    if not want:
        raise SystemExit(f"{name} isn't listed in the {PBS_RELEASE} SHA256SUMS")
    arc = fetch(f"{PBS_BASE}/{name.replace('+', '%2B')}", cache_dir() / name)
    got = hashlib.sha256(arc.read_bytes()).hexdigest()
    if got != want:
        arc.unlink()
        raise SystemExit(f"checksum mismatch for {name}: {got} != {want}")
    return arc


def site_packages(py_root: Path, os_name: str) -> Path:
    return py_root / "Lib" / "site-packages" if os_name == "windows" else py_root / "lib" / f"python{PY_SHORT}" / "site-packages"


def requirements_for(target: dict) -> str:
    """requirements-desktop.txt (plus the target's extra file, e.g. the Mac window) with the target's own pins swapped in."""
    pins = target.get("pins") or {}
    out = []
    lines = (HERE / "requirements-desktop.txt").read_text().splitlines()
    if target.get("extra_requirements"):
        lines += (HERE / target["extra_requirements"]).read_text().splitlines()
    for ln in lines:
        name = ln.split("==", 1)[0].strip()
        out.append(f"{name}=={pins[name]}" if name in pins and "==" in ln else ln)
    return "\n".join(out) + "\n"


def install_wheels(target: dict, dest: Path) -> None:
    req = dest.parent / "opensoul-requirements.txt"
    dest.mkdir(parents=True, exist_ok=True)
    req.write_text(requirements_for(target))
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--no-compile", "--target", str(dest),
           "--only-binary=:all:", "--python-version", PY_SHORT, "--implementation", "cp",
           "--abi", "cp312", "--abi", "abi3", "--abi", "none", "--upgrade",
           "-r", str(req)]
    for p in target["platforms"]:
        cmd += ["--platform", p]
    if "proxy_tools==" in req.read_text():
        cmd += ["--find-links", str(proxy_tools_wheel())]
    log("installing pinned wheels for " + target["triple"])
    try:
        subprocess.run(cmd, check=True, env=dict(os.environ, PIP_DISABLE_PIP_VERSION_CHECK="1"))
    finally:
        req.unlink(missing_ok=True)


def proxy_tools_wheel() -> Path:
    """pywebview needs proxy_tools, which PyPI only has as source: build its (pure Python) wheel from the checked sdist."""
    sdist = fetch(PROXY_TOOLS_SDIST, cache_dir() / "proxy_tools-0.1.0.tar.gz")
    got = hashlib.sha256(sdist.read_bytes()).hexdigest()
    if got != PROXY_TOOLS_SDIST_SHA256:
        sdist.unlink()
        raise SystemExit(f"checksum mismatch for proxy_tools-0.1.0.tar.gz: {got}")
    wheels = cache_dir() / "wheels"
    if not list(wheels.glob("proxy_tools-0.1.0-py3-none-any.whl")):
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--quiet", "--no-deps", "--no-binary", ":all:",
                        str(sdist), "-w", str(wheels)], check=True)
    return wheels


def export_app(ref: str, dest: Path) -> str:
    sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", ref], check=True, capture_output=True,
                         text=True).stdout.strip()
    data = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", ref], check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        members = [m for m in tf.getmembers() if not m.name.startswith(EXCLUDE_TOP)]
        tf.extractall(dest, members=members, filter="data") if sys.version_info >= (3, 12) else tf.extractall(dest, members=members)
    return sha


# Every slot macOS reads (type, pixels): 16/32/64/128/256/512/1024 px plus the @2x ones, all PNG-encoded (macOS 10.7+).
ICNS_TYPES = ((b"icp4", 16), (b"icp5", 32), (b"icp6", 64), (b"ic07", 128), (b"ic08", 256), (b"ic09", 512),
              (b"ic10", 1024), (b"ic11", 32), (b"ic12", 64), (b"ic13", 256), (b"ic14", 512))


def write_icns(im, dest: Path) -> Path:
    """A complete .icns from one big RGBA image. The format is just "icns", a length, then (type, length, PNG) entries;
    written here because Pillow skips the 16 and 32 px slots and iconutil only exists on macOS."""
    from PIL import Image

    body = b""
    for kind, n in ICNS_TYPES:
        buf = io.BytesIO()
        im.resize((n, n), Image.LANCZOS).save(buf, "PNG", optimize=True)
        data = buf.getvalue()
        body += kind + (8 + len(data)).to_bytes(4, "big") + data
    dest.write_bytes(b"icns" + (8 + len(body)).to_bytes(4, "big") + body)
    return dest


def make_icon(stage: Path) -> dict[str, Path]:
    """The app icon from the 1024 px master (packaging/icon/OpenSoul-1024.png, made from opensoul-icon.svg by
    packaging/make_icon.py): .icns (every size 16-1024, write_icns), .ico and .png; no iconutil needed."""
    from PIL import Image

    im = Image.open(ICON_MASTER).convert("RGBA")
    if im.size != (1024, 1024):
        im = im.resize((1024, 1024), Image.LANCZOS)
    out = {"png": stage / "OpenSoul.png", "icns": stage / "OpenSoul.icns", "ico": stage / "OpenSoul.ico"}
    im.resize((512, 512), Image.LANCZOS).save(out["png"])
    write_icns(im, out["icns"])
    im.save(out["ico"], sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return out


def _write(p: Path, text: str, exe: bool = False) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")
    if exe:
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def render(name: str, **kw: str) -> str:
    text = (HERE / "templates" / name).read_text(encoding="utf-8")
    kw.setdefault("BUNDLE_ID", BUNDLE_ID)
    for k, v in kw.items():
        text = text.replace("@" + k + "@", v)
    return text


def build_runtime(tname: str, runtime: Path, ref: str) -> str:
    t = TARGETS[tname]
    with tarfile.open(python_archive(t["triple"])) as tf:
        if sys.version_info >= (3, 12):
            tf.extractall(runtime, filter="tar")
        else:
            tf.extractall(runtime)
    py = runtime / "python"
    sp = site_packages(py, t["os"])
    install_wheels(t, sp)
    sha = export_app(ref, runtime / "app")
    # The app folder goes on sys.path through a .pth file, so the launcher can run Python isolated (-I) and ignore
    # whatever PYTHONPATH or user site-packages the computer already has.
    rel = os.path.relpath(runtime / "app", sp)
    (sp / "opensoul_app.pth").write_text(rel.replace(os.sep, "/") + "\n", encoding="utf-8")
    return sha


def version_string(sha: str) -> str:
    ns: dict = {}
    exec((ROOT / "opensoul" / "__init__.py").read_text().split("from opensoul")[0], ns)
    return f"{ns['__version__']}-{sha}"


def package(tname: str, out_dir: Path, ref: str) -> Path:
    t = TARGETS[tname]
    stage = out_dir / f"stage-{tname}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    icons = make_icon(stage)
    if t["os"] == "mac":
        app = stage / "OpenSoul.app"
        res = app / "Contents" / "Resources"
        sha = build_runtime(tname, res / "runtime", ref)
        ver = version_string(sha)
        (res / "VERSION").write_text(ver + "\n")
        shutil.copy(icons["icns"], res / "OpenSoul.icns")
        shutil.copy(icons["png"], res / "OpenSoul.png")
        _write(app / "Contents" / "Info.plist", render("Info.plist", VERSION=ver, SHORT=ver.split("-")[0],
                                                        BUNDLE_ID=BUNDLE_ID))
        _write(app / "Contents" / "MacOS" / "OpenSoul", render("mac_launcher.sh", ARCH=t["arch"]), exe=True)
        _write(stage / "How to open OpenSoul.txt", render("HOW_TO_OPEN_mac.txt"))
        top = ["OpenSoul.app", "How to open OpenSoul.txt"]
    elif t["os"] == "linux":
        root = stage / "OpenSoul"
        sha = build_runtime(tname, root / "runtime", ref)
        ver = version_string(sha)
        (root / "VERSION").write_text(ver + "\n")
        shutil.copy(icons["png"], root / "OpenSoul.png")
        _write(root / "OpenSoul", render("linux_launcher.sh", ARCH=t["arch"]), exe=True)
        _write(root / "install-desktop-entry.sh", render("linux_desktop_entry.sh"), exe=True)
        _write(root / "HOW_TO_OPEN.txt", render("HOW_TO_OPEN_linux.txt"))
        top = ["OpenSoul"]
    else:
        root = stage / "OpenSoul"
        sha = build_runtime(tname, root / "runtime", ref)
        ver = version_string(sha)
        (root / "VERSION").write_text(ver + "\r\n")
        shutil.copy(icons["ico"], root / "OpenSoul.ico")
        (root / "OpenSoul.cmd").write_text(render("windows_launcher.cmd").replace("\n", "\r\n"), encoding="utf-8")
        (root / "HOW TO OPEN.txt").write_text(render("HOW_TO_OPEN_windows.txt").replace("\n", "\r\n"), encoding="utf-8")
        top = ["OpenSoul"]
    name = f"OpenSoul-{ver}-{tname}"
    if t["os"] == "linux":
        dest = out_dir / f"{name}.tar.gz"
        with tarfile.open(dest, "w:gz") as tf:
            for item in top:
                tf.add(stage / item, arcname=item)
    else:
        dest = out_dir / f"{name}.zip"
        zip_tree(stage, top, dest)
    manifest = {"target": tname, "version": ver, "ref": ref, "python": PY_VERSION, "pbs_release": PBS_RELEASE,
                "file": dest.name, "bytes": dest.stat().st_size, "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
                "built": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    (out_dir / f"{name}.json").write_text(json.dumps(manifest, indent=2) + "\n")
    log(f"wrote {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    return dest


def zip_tree(base: Path, top: list[str], dest: Path) -> None:
    """Zip that keeps Unix permissions and symlinks, so the Mac's Archive Utility restores a runnable .app."""
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for item in top:
            p0 = base / item
            paths = [p0] if p0.is_file() else [p0, *sorted(p0.rglob("*"))]
            for p in paths:
                arc = p.relative_to(base).as_posix()
                st = os.lstat(p)
                if stat.S_ISLNK(st.st_mode):
                    zi = zipfile.ZipInfo(arc, time.localtime(st.st_mtime)[:6])
                    zi.create_system = 3
                    zi.external_attr = (stat.S_IFLNK | 0o755) << 16
                    zf.writestr(zi, os.readlink(p))
                elif p.is_dir():
                    zi = zipfile.ZipInfo(arc + "/", time.localtime(st.st_mtime)[:6])
                    zi.create_system = 3
                    zi.external_attr = (stat.S_IFDIR | 0o755) << 16 | 0x10
                    zf.writestr(zi, b"")
                else:
                    zi = zipfile.ZipInfo(arc, time.localtime(max(st.st_mtime, 315532800))[:6])
                    zi.create_system = 3
                    zi.external_attr = (stat.S_IFREG | (st.st_mode & 0o777)) << 16
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    with open(p, "rb") as fh:
                        zf.writestr(zi, fh.read())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--target", required=True, choices=sorted(TARGETS))
    ap.add_argument("--ref", default="HEAD", help="git ref to package (default HEAD; only committed files ship)")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--keep-stage", action="store_true", help="keep the unpacked stage folder (for smoke tests)")
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    package(a.target, out, a.ref)
    if not a.keep_stage:
        shutil.rmtree(out / f"stage-{a.target}", ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
