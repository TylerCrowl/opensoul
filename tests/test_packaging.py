"""Desktop packages (packaging/build_bundle.py, docs/DESKTOP.md): templates, archive layout, pins, install scripts.
No downloads here: the full build is exercised by the desktop CI workflow and by hand (docs/DESKTOP.md)."""
import importlib.util
import os
import re
import shutil
import stat
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packaging"
spec = importlib.util.spec_from_file_location("build_bundle", PKG / "build_bundle.py")
BB = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BB)

TEMPLATES = sorted((PKG / "templates").iterdir())
SCRIPTS = [PKG / "templates" / n for n in ("mac_launcher.sh", "linux_launcher.sh", "linux_desktop_entry.sh")] + \
          [ROOT / "scripts" / "install.sh"]


def test_every_template_renders_without_leftover_placeholders():
    for t in TEMPLATES:
        out = BB.render(t.name, ARCH="arm64", VERSION="0.1.0-abc1234", SHORT="0.1.0")
        assert not re.search(r"@[A-Z]+@", out), t.name


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_shell_scripts_parse_and_never_need_admin_or_weaken_security(script):
    if not shutil.which("bash"):
        pytest.skip("no bash")
    subprocess.run(["bash", "-n", str(script)], check=True)
    text = "\n".join(ln for ln in script.read_text().splitlines() if not ln.lstrip().startswith("#"))
    for bad in ("sudo ", "spctl", "sysctl -w", "--master-disable", "ufw ", "iptables"):
        assert bad not in text, (script.name, bad)


def test_launchers_run_python_isolated_from_the_users_environment():
    for name in ("mac_launcher.sh", "linux_launcher.sh", "windows_launcher.cmd"):
        assert "-I -m opensoul.launcher" in (PKG / "templates" / name).read_text(), name


def test_mac_launcher_only_clears_quarantine_on_its_own_copy():
    text = (PKG / "templates" / "mac_launcher.sh").read_text()
    lines = [ln for ln in text.splitlines() if "xattr" in ln and not ln.lstrip().startswith("#")]
    assert lines and all('"$RT.partial"' in ln for ln in lines)
    assert "Application Support/OpenSoul" in text


def test_info_plist_is_valid():
    import plistlib

    d = plistlib.loads(BB.render("Info.plist", VERSION="0.1.0-abc", SHORT="0.1.0").encode())
    assert d["CFBundleExecutable"] == "OpenSoul" and d["CFBundlePackageType"] == "APPL"
    assert d["LSMinimumSystemVersion"] == "13.0"
    assert d["CFBundleName"] == d["CFBundleDisplayName"] == "OpenSoul"
    assert d["CFBundleIdentifier"] == "org.opensoul.app" == BB.BUNDLE_ID
    assert d["CFBundleShortVersionString"] == d["CFBundleVersion"] == "0.1.0" and d["OpenSoulBuild"] == "0.1.0-abc"
    assert d["CFBundleIconFile"] == "OpenSoul" and d["NSHighResolutionCapable"] is True
    assert d["NSAppTransportSecurity"] == {"NSAllowsLocalNetworking": True}


def test_how_to_open_notes_cover_gatekeeper_and_smartscreen():
    mac = (PKG / "templates" / "HOW_TO_OPEN_mac.txt").read_text()
    assert "right-click" in mac and "Open Anyway" in mac and "Privacy & Security" in mac
    assert "Run anyway" in (PKG / "templates" / "HOW_TO_OPEN_windows.txt").read_text()


def test_every_runtime_dependency_is_pinned_for_the_desktop():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    names = {re.split(r"[<>=!~ ;\[]", d, maxsplit=1)[0].lower().replace("_", "-") for d in deps}
    pins = {}
    for ln in (PKG / "requirements-desktop.txt").read_text().splitlines():
        ln = ln.split("#", 1)[0].strip()
        if ln:
            n, v = ln.split("==")
            pins[n.lower().replace("_", "-")] = v
    assert names <= set(pins), names - set(pins)
    assert "imageio-ffmpeg" in pins  # Macs and Windows have no system ffmpeg


def test_targets_cover_mac_windows_linux():
    assert {"mac-arm64", "mac-x64", "windows-x64", "linux-x64", "linux-arm64"} <= set(BB.TARGETS)
    assert all(t["platforms"] for t in BB.TARGETS.values())


def test_dev_only_folders_stay_out_of_packages():
    for top in ("tests/", "notes/", "docs/evidence/", "docs/drafts/"):
        assert top in BB.EXCLUDE_TOP


def test_zip_keeps_exec_bits_and_symlinks(tmp_path):
    base = tmp_path / "b"
    app = base / "OpenSoul.app" / "Contents" / "MacOS"
    app.mkdir(parents=True)
    exe = app / "OpenSoul"
    exe.write_text("#!/bin/bash\n")
    exe.chmod(0o755)
    (app / "link").symlink_to("OpenSoul")
    (base / "note.txt").write_text("hi")
    dest = tmp_path / "x.zip"
    BB.zip_tree(base, ["OpenSoul.app", "note.txt"], dest)
    with zipfile.ZipFile(dest) as zf:
        info = {i.filename: i for i in zf.infolist()}
        mode = info["OpenSoul.app/Contents/MacOS/OpenSoul"].external_attr >> 16
        assert stat.S_ISREG(mode) and mode & 0o111
        link = info["OpenSoul.app/Contents/MacOS/link"]
        assert stat.S_ISLNK(link.external_attr >> 16) and zf.read(link) == b"OpenSoul"
        assert "note.txt" in info and "OpenSoul.app/" in info


def test_icon_files(tmp_path):
    out = BB.make_icon(tmp_path)
    for k in ("png", "icns", "ico"):
        assert out[k].is_file() and out[k].stat().st_size > 1000
    assert out["icns"].read_bytes()[:4] == b"icns"


def test_icns_has_every_size_macos_reads(tmp_path):
    from PIL import IcnsImagePlugin, Image

    out = BB.make_icon(tmp_path)
    data = out["icns"].read_bytes()
    assert int.from_bytes(data[4:8], "big") == len(data)
    with open(out["icns"], "rb") as fh:
        f = IcnsImagePlugin.IcnsFile(fh)
        kinds = set(f.dct)
        sizes = set(f.itersizes())
    assert {k for k, _ in BB.ICNS_TYPES} <= kinds
    assert {(16, 16, 1), (32, 32, 1), (64, 64, 1), (128, 128, 1), (256, 256, 1), (512, 512, 1), (512, 512, 2),
            (16, 16, 2), (32, 32, 2), (128, 128, 2), (256, 256, 2)} <= sizes
    im = Image.open(out["icns"])
    assert im.size == (1024, 1024) and im.mode == "RGBA"
    assert im.getpixel((512, 512))[3] == 255 and im.getpixel((2, 2))[3] == 0  # opaque middle, transparent corner


def test_icon_master_matches_the_svg_and_is_clean():
    from PIL import Image

    im = Image.open(BB.ICON_MASTER)
    assert im.size == (1024, 1024) and im.mode == "RGBA"
    assert not {k for k in im.info if k.lower() in ("comment", "description", "author", "software", "xml:com.adobe.xmp")}
    svg = (ROOT / "app" / "web" / "static" / "opensoul-icon.svg").read_text()
    assert 'viewBox="0 0 1024 1024"' in svg and "<image" not in svg and "href=\"http" not in svg  # all original vector


def test_mac_packages_bundle_the_window_and_pin_it():
    for name in ("mac-arm64", "mac-x64"):
        txt = BB.requirements_for(BB.TARGETS[name])
        for pkg in ("pywebview==6.2.1", "pyobjc-core==", "pyobjc-framework-Cocoa==", "pyobjc-framework-WebKit==",
                    "proxy_tools==0.1.0", "bottle=="):
            assert pkg in txt, (name, pkg)
        assert "macosx_10_13_universal2" in BB.TARGETS[name]["platforms"]  # where PyObjC's wheels are tagged
    for name in ("linux-x64", "linux-arm64", "windows-x64"):
        assert "pywebview" not in BB.requirements_for(BB.TARGETS[name])
    for ln in (PKG / "requirements-desktop-mac.txt").read_text().splitlines():
        ln = ln.split("#", 1)[0].strip()
        assert not ln or re.fullmatch(r"[A-Za-z0-9_.-]+==[0-9][A-Za-z0-9.]*", ln), ln
    assert re.fullmatch(r"[0-9a-f]{64}", BB.PROXY_TOOLS_SDIST_SHA256)


def test_mac_launcher_execs_the_app_and_offers_the_move_first():
    text = (PKG / "templates" / "mac_launcher.sh").read_text()
    move = text.index("-m opensoul.mac_move")
    run = text.index("exec \"$RT/python/bin/python3\" -I -m opensoul.launcher open")
    assert move < run and "OPENSOUL_APP=mac" in text and "OpenSoul.icns" in text
    assert "[ $? -eq 3 ] && exit 0" in text


def test_make_dmg_is_mac_only_and_draws_its_own_background(tmp_path):
    spec2 = importlib.util.spec_from_file_location("make_dmg", PKG / "make_dmg.py")
    md = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(md)
    from PIL import Image

    bg = md.background(tmp_path / "bg.png", scale=2)
    assert Image.open(bg).size == (md.W * 2, md.H * 2)
    s = md.settings(Path("/x/OpenSoul.app"), bg, None)
    assert s["symlinks"] == {"Applications": "/Applications"} and set(s["icon_locations"]) == {"OpenSoul.app", "Applications"}
    if os.uname().sysname != "Darwin":
        with pytest.raises(SystemExit):
            md.main([str(tmp_path / "OpenSoul.app"), str(tmp_path / "x.dmg")])


def test_ci_builds_the_dmg_on_macos():
    wf = (ROOT / ".github" / "workflows" / "desktop.yml").read_text()
    assert "packaging/make_dmg.py" in wf and "dmgbuild==" in wf and "hdiutil verify" in wf


def test_desktop_ci_workflow_builds_and_smoke_tests_every_target():
    import yaml

    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "desktop.yml").read_text())
    jobs = wf["jobs"]
    assert set(jobs["build"]["strategy"]["matrix"]["target"]) == set(BB.TARGETS)
    assert {i["target"] for i in jobs["smoke"]["strategy"]["matrix"]["include"]} == set(BB.TARGETS)
    on = wf.get("on", wf.get(True))
    assert "workflow_dispatch" in on and "release" not in on  # never publishes by itself


def test_install_sh_refuses_the_wrong_package(tmp_path):
    if os.uname().sysname != "Linux" or not shutil.which("bash"):
        pytest.skip("linux only")
    wrong = tmp_path / "OpenSoul-0.1.0-x-windows-x64.zip"
    wrong.write_bytes(b"x")
    r = subprocess.run(["bash", str(ROOT / "scripts" / "install.sh"), str(wrong)], capture_output=True, text=True,
                       env={**os.environ, "HOME": str(tmp_path), "OPENSOUL_NO_OPEN": "1"})
    assert r.returncode != 0 and "isn't the" in r.stderr


def test_target_pins_override_the_shared_list():
    txt = BB.requirements_for(BB.TARGETS["mac-x64"])
    assert "opencv-python-headless==4.12.0.88" in txt and "numpy==" in txt
    shared = (PKG / "requirements-desktop.txt").read_text().rstrip("\n") + "\n"
    assert BB.requirements_for(BB.TARGETS["linux-x64"]) == shared  # no pins of its own: the shared list as is
    mac = (PKG / "requirements-desktop-mac.txt").read_text().rstrip("\n") + "\n"
    assert BB.requirements_for(BB.TARGETS["mac-arm64"]) == shared + mac  # plus the Mac window, nothing overridden
