# One-line install of the OpenSoul desktop package for Windows (current user only, no administrator rights).
#
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Package OpenSoul-<ver>-windows-x64.zip
#   $env:OPENSOUL_RELEASE_BASE="<releases-url>"; irm <raw-url>/scripts/install.ps1 | iex
#
# Unpacks to %LOCALAPPDATA%\Programs\OpenSoul, adds a Start Menu shortcut and opens OpenSoul. Changes no system,
# network or firewall settings. Packages are built by packaging/build_bundle.py.
param([string]$Package = "")
$ErrorActionPreference = "Stop"
if (-not [Environment]::Is64BitOperatingSystem) { throw "OpenSoul needs 64-bit Windows." }
if (-not $Package) {
  if (-not $env:OPENSOUL_RELEASE_BASE) { throw "Give -Package <zip or URL>, or set OPENSOUL_RELEASE_BASE." }
  $Package = ($env:OPENSOUL_RELEASE_BASE.TrimEnd("/")) + "/OpenSoul-latest-windows-x64.zip"
}
if ($Package -notmatch "windows-x64") { throw "$Package isn't the windows-x64 package." }
$tmp = Join-Path $env:TEMP ("opensoul-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tmp | Out-Null
try {
  $zip = Join-Path $tmp "pkg.zip"
  if (Test-Path $Package) { Copy-Item $Package $zip } else { Write-Host "Downloading $Package"; Invoke-WebRequest -Uri $Package -OutFile $zip -UseBasicParsing }
  Unblock-File $zip
  $dest = Join-Path $env:LOCALAPPDATA "Programs"
  New-Item -ItemType Directory -Force -Path $dest | Out-Null
  if (Test-Path (Join-Path $dest "OpenSoul")) { Remove-Item -Recurse -Force (Join-Path $dest "OpenSoul") }
  Expand-Archive -Path $zip -DestinationPath $dest
  $app = Join-Path $dest "OpenSoul"
  Get-ChildItem -Recurse $app | Unblock-File
  $lnk = Join-Path ([Environment]::GetFolderPath("Programs")) "OpenSoul.lnk"
  $sh = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
  $sh.TargetPath = Join-Path $app "OpenSoul.cmd"
  $sh.WorkingDirectory = $app
  $sh.IconLocation = Join-Path $app "OpenSoul.ico"
  $sh.WindowStyle = 7
  $sh.Save()
  Write-Host "Installed $app (Start Menu: OpenSoul)"
  if ($env:OPENSOUL_NO_OPEN -ne "1") { Start-Process (Join-Path $app "OpenSoul.cmd") -WindowStyle Hidden }
} finally { Remove-Item -Recurse -Force $tmp }
