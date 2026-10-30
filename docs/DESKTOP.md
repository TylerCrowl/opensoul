# Desktop app: one click, no terminal

Status: **experimental**. We built the Linux x64 package and did a basic test on CPU. The package starts, shows the welcome page and stops.

We cross-build the Mac and Windows packages from the same recipe. We check their file layout here. They still need a first open on a real Mac or Windows PC. The `desktop` CI workflow does this: it opens each package on its own OS.

## What you get

| Computer | Package | How to open |
|---|---|---|
| Mac with an Apple chip (M1 or newer), macOS 13+ | `OpenSoul-<ver>-mac-arm64.dmg` (drag to Applications) or `.zip` → `OpenSoul.app` | Double-click. First time: right-click → **Open**. It has its own window and Dock icon. |
| Intel Mac, macOS 13+ | `OpenSoul-<ver>-mac-x64.dmg` or `.zip` | Same as above |
| Windows 10/11, 64-bit | `OpenSoul-<ver>-windows-x64.zip` → `OpenSoul\OpenSoul.cmd` | Click **Extract All**. Double-click `OpenSoul.cmd`. |
| Linux x64 / arm64 (incl. DGX Spark) | `OpenSoul-<ver>-linux-<arch>.tar.gz` → `OpenSoul/OpenSoul` | Unpack. Double-click it or run it. |

Each package carries its own Python 3.12 ([python-build-standalone](https://github.com/astral-sh/python-build-standalone),
checksum-checked) and every library the app needs. The build installs them from the pinned
[packaging/requirements-desktop.txt](../packaging/requirements-desktop.txt). Macs also get
[packaging/requirements-desktop-mac.txt](../packaging/requirements-desktop-mac.txt) for the app window.
To open the app, you need **no internet, no Python, no Homebrew and no admin password**. The app installs nothing
system-wide. It changes no network, firewall or VPN settings.

You can also install from a terminal with one line. It installs for your user only (no sudo). The app goes in
`~/Applications` or `~/.local/opt`.

```bash
./scripts/install.sh OpenSoul-<ver>-mac-arm64.zip           # macOS / Linux, a package file or URL
```
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Package OpenSoul-<ver>-windows-x64.zip
```

## First run

1. The launcher (`opensoul/launcher.py`) starts the OpenSoul server in the background on `127.0.0.1`. It uses port
   7860, or the next free port. On a Mac, OpenSoul then opens in its own window (see *The Mac app* below). On Linux
   and Windows, your browser opens. If OpenSoul is already running, a second double-click shows it again.
2. The **welcome page** (`/welcome`) tells you about this computer. It uses the same local, read-only hardware check
   as the Models tab. It shows the six steps of the app's top bar. It also names **Music videos** and **Shorts**,
   on the right of the top bar. It gives two choices:
   - **Try it now** (Preview mode, `OPENSOUL_DRY_RUN=1`): this works on any computer, with no graphics card. You see
     sample pictures and clips while you learn the steps. Nothing leaves the computer.
   - **Connect my studio**: type the address of a computer that runs ComfyUI, for example a DGX Spark. Then click
     **Test connection**. OpenSoul asks ComfyUI's `/system_stats` one time. It shows the ComfyUI version, GPU and
     memory that it found. Then it checks that the studio's `comfy-api-proxy` also answers.
   - **The API helper port**: the proxy uses the same host and port 8189 by default. To change the port, open
     **Advanced**. When you save, the app uses the studio immediately, with no restart. Read *Connecting your studio
     safely* below.
3. **Ready**: open the app. In studio mode, the page links to the **Models** tab. That tab shows the open models on
   the studio.

A small chip in the corner of the app shows *Preview mode* or *Studio connected*. It has **Change** (opens the
welcome page again) and **Quit** (stops the background server). OpenSoul saves your choice in `launcher.json`.

This computer must be able to connect to the studio. Read the next section.

## Connecting your studio safely

The welcome page has two small panels under **Connect my studio**: *Is this safe?* and *Where do I find this
address?* This section gives the same information, with more detail.

**What OpenSoul does, and does not do.** The code is in `opensoul/launcher.py` and `app/launcher_routes.py`.

- OpenSoul talks only to the studio address that you type. It also talks to that studio's API helper, the
  `comfy-api-proxy`, on port 8189 of the same computer. You can change that port under **Advanced**. The connection
  uses only your own network.
- The connection check goes directly to that address. It ignores proxy settings on this computer. It never follows a
  redirect to a different address.
- When you save a studio, OpenSoul adds its address to `NO_PROXY`. Thus the render calls also go directly to the
  studio.
- There is no OpenSoul account, cloud server or telemetry. Your prompts, pictures and videos go only between this
  computer and your studio. When you open OpenSoul from the desktop app, it listens only on `127.0.0.1` (this
  computer).
- OpenSoul sends generation jobs (prompts, reference pictures and the workflow) to ComfyUI. It gets the finished
  pictures, videos and voices back. **Test connection** sends one `GET /system_stats` to ComfyUI and one `GET /` to
  the API helper. The test changes nothing.
- To download models, you do a separate step on the studio (`scripts/download_models.sh`, shown on the Models tab).
  The welcome page never downloads models or other files.
- The only other network use is a normal name lookup (DNS or `.local` discovery). This occurs when you type a name
  instead of a number.

**The one caveat.** By default, ComfyUI has no password, so anyone on the same network can use it. Connect only on
a network that you trust, for example your home network. Do not type a public internet address. When you are away
from home, use a private connection such as a VPN. Do not open ComfyUI to the internet.

**How the app checks the address that you type:**

| You type | Result |
|---|---|
| A home-network address: `10/8`, `172.16/12`, `192.168/16` | Accepted |
| A VPN or carrier address in `100.64/10`, a link-local address (`169.254/16`, `fe80::`), a private IPv6 address (`fc00::/7`) | Accepted |
| This computer: `localhost`, `127.0.0.1`, `::1` | Accepted |
| A `.local` name (for example `my-studio.local`), or a name for one of the addresses above | Accepted |
| An address on the public internet, or a name for one | Allowed, with a clear warning on the welcome page |
| An address that does not start with `http://` or `https://` (`file:`, `ftp:`, `javascript:`, …) | Refused |
| A user name or password in the address (`http://user:pass@…`) | Refused |
| `0.0.0.0` | Refused, with a hint: the studio listens on `0.0.0.0`, but that is not its address |

Why a warning and not a block for public addresses? Some real setups use addresses that count as "public". For
example, many home networks give each device a public IPv6 address, and some VPNs use public ranges. A block would
stop those people with no way forward. The warning tells all other people the risk.

**Test connection** tells you what it found before you continue. It shows the ComfyUI version, the graphics card and
its memory (from ComfyUI's `/system_stats`). It also shows if the API helper answers. If the test fails, it tells you
the cause:

- OpenSoul cannot find the name.
- Nothing answered on that port.
- There was no answer.
- Something answered, but it is not ComfyUI. This is often the wrong port: ComfyUI uses 8188 and the API helper
  uses 8189.
- The API helper is missing.

**Continue** stays off until you test the address in the box. After a failed test or a warning, the button shows
*Continue anyway*.

### Where do I find the studio's address?

1. **Let other computers connect to the studio.** ComfyUI answers only on its own computer until you start it with
   `--listen`. On the studio, start ComfyUI on its home-network address. For example:
   `python main.py --listen <studio address> --port 8188`.

   `--listen` alone means "every network that this computer is on". This is more than you need. Use it only on a
   network that you trust. Never use it on public Wi-Fi.

   The API helper (`comfy-api-proxy`) must also accept connections, on port 8189. `comfy-api-proxy --help` shows how.
   `scripts/setup_spark.sh` starts both on `127.0.0.1` intentionally. OpenSoul never changes that for you.
2. **Find the address.**
   - DGX Spark or another Linux computer: open a Terminal on it. Run `hostname -I`. Use the first number. It often
     starts with 192.168. or 10. Its name plus `.local` often works too.
   - Mac: open System Settings → Wi-Fi (or Network). Click **Details…** next to your network. It shows the IP address.
     System Settings → General → Sharing → *Local hostname* gives a `.local` name.
   - Windows: open Settings → Network & internet → **Properties**. Find the IPv4 address.
3. **Type the address.** Put `http://` in front and `:8188` at the end, for example `http://my-studio.local:8188`.
   Then click **Test connection**.

## Where things live

| | macOS | Windows | Linux |
|---|---|---|---|
| Settings, characters, renders, logs | `~/Library/Application Support/OpenSoul` | `%LOCALAPPDATA%\OpenSoul` | `~/.local/share/opensoul` |

That folder contains:

- `launcher.json`: the mode and the studio address.
- `data/`: what the app makes (`OPENSOUL_DATA`).
- `logs/server.log`.
- `server.json`: the port and process ID while OpenSoul runs.

On a Mac, the first open also copies the app's private runtime to `runtime/<version>/` in that folder. Then the app
runs from a normal folder that it can write to, even when macOS opened it from a temporary location. To keep all of
this in a different folder, set `OPENSOUL_LAUNCHER_HOME`.

Commands (the same on every OS, with the package's own Python): `opensoul.launcher open | serve | stop | status`.
On Linux: `./OpenSoul/OpenSoul stop`.

## The Mac app

`OpenSoul.app` works like any other Mac app:

- **Icon.** The OpenSoul icon (`packaging/icon/OpenSoul-1024.png`, made from `app/web/static/opensoul-icon.svg`)
  is in `Contents/Resources/OpenSoul.icns`. It has every size from 16 to 1024 px. Thus it shows in Finder,
  Applications, Launchpad and the Dock. `Info.plist` has: the name and display name *OpenSoul*, the identifier
  `org.opensoul.app`, the version, macOS 13 or newer, and Retina support (`NSHighResolutionCapable`).
- **Its own window.** OpenSoul opens in a native window, not a browser tab. The window uses pywebview on Apple's
  WKWebView (`opensoul/desktop_window.py`). The window loads only OpenSoul's own server on `127.0.0.1`. Other links
  open in your browser. Exported stories and clips go to your Downloads folder.
- **Quitting.** Close the window, press Command-Q or click **Quit** in the corner of the app. All three stop the
  background server correctly. The corner **Quit** also closes the window.
- **Browser fallback.** If the window cannot open, OpenSoul opens in your browser. To always use the browser, set
  `OPENSOUL_WINDOW=0`. To try the window on Linux or Windows, set `OPENSOUL_WINDOW=1`. This needs pywebview and a GUI
  backend on that computer. The Linux and Windows packages do not include one.
- **Move to Applications.** When you open OpenSoul from Downloads, it asks one time: *Move to Applications* or
  *Not Now* (`opensoul/mac_move.py`). It never moves without your click. The move is a rename on the same disk:
  OpenSoul copies and deletes nothing. OpenSoul remembers *Not Now*.
- **Disk image.** The `.dmg` shows OpenSoul next to an Applications shortcut, with an arrow. Drag OpenSoul onto the
  shortcut. The `.dmg` needs macOS's `hdiutil`. Thus the macOS jobs of the `desktop` CI workflow make it
  (`packaging/make_dmg.py`, dmgbuild). On Linux, `build_bundle.py` makes only the `.zip`.

We checked these items on Linux:

- The bundle layout, `Info.plist`, every `.icns` size and the bundled window libraries.
- The launcher and move logic, with unit tests that use a fake window and fake dialogs.

These items need a first open on a real Mac (or the CI macOS job):

- The window, the Dock name and icon, and Command-Q.
- Downloads from the window, the Move dialog and the `.dmg`.

## The one-time security prompt

We did not sign the packages with an Apple Developer ID or a Windows code-signing certificate. Both cost money and would connect the project to a personal identity. Thus the first open shows a warning:

- **macOS 13–14:** right-click (or Control-click) OpenSoul → **Open** → **Open**. You do this one time.
- **macOS 15 and newer:** the right-click menu can show only *Done*. Open **System Settings → Privacy & Security**. Scroll to *"OpenSoul" was blocked*. Click **Open Anyway**. Confirm.
- **Still blocked, or do you prefer Terminal?** Run `xattr -dr com.apple.quarantine /Applications/OpenSoul.app`. This removes the download flag from this app only. `scripts/install.sh` does the same.
- **Windows SmartScreen:** *Windows protected your PC* → **More info** → **Run anyway**.

We do not ask you to make system-wide protection weaker (no `spctl --master-disable`, no sysctl changes).

## Building the packages

```bash
python packaging/build_bundle.py --target mac-arm64      # or mac-x64, linux-x64, linux-arm64, windows-x64
```

The build runs on any OS with Python 3.10+, pip and Pillow (for the icon files). Cross-builds work because the build
gets the wheels for the target platform. It needs the internet one time (Python and wheels, cached in
`~/.cache/opensoul-build`).

The build takes the app from `git archive <ref>` (default `HEAD`). Thus a package contains only committed files:
never `data/`, local renders or untracked files. It also excludes `tests/`, `notes/`, `tools/`, `docs/evidence/` and
`docs/drafts/`. The output goes to `dist/`: the archive and a small JSON manifest (version, size, sha256).

[.github/workflows/desktop.yml](../.github/workflows/desktop.yml) builds all five packages on Linux. Then it opens
each package on its own OS (macOS arm64 and Intel, Windows, Linux x64 and arm64) and checks `/api/launcher/status`.
It also ad-hoc signs the Mac app, checks that the bundled window libraries import, and makes the drag-to-Applications
`.dmg` (`packaging/make_dmg.py`). You start it by hand, or a `v*` tag starts it. It only uploads workflow artifacts.

Sizes (0.1.0): the Mac arm64 zip is about 115 MB (about 300 MB unpacked). Linux x64 is about 180 MB. Most of this is
OpenCV, NumPy and a static ffmpeg.

## Not built yet

- A signed and notarized Mac build, and a signed Windows installer. These need certificates.
- A `.dmg` from Linux. This needs macOS `hdiutil`. The macOS jobs of the CI workflow make it.
- ComfyUI and the models in the package. The package is the app only. Real renders need a studio (read SETUP.md).
- Auto-update. To update, download the new package and open it. You can delete old runtimes under `runtime/` by hand.

Idea credit: the MIT-licensed Open Generative AI project (github.com/Anil-matcha/Open-Generative-AI) gave us the idea for the one-click download table and the Gatekeeper / SmartScreen steps. We use no code from it. Its app is an Electron front end for a hosted API. OpenSoul is a private Python runtime for a local server.
