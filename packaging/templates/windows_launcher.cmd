@echo off
rem OpenSoul for Windows: runs its private Python from this folder, starts OpenSoul in the background and opens
rem the browser (opensoul\launcher.py). Nothing is installed system-wide and no administrator rights are needed.
setlocal
set "HERE=%~dp0"
cd /d "%HERE%runtime\app" || exit /b 1
start "" /b "%HERE%runtime\python\pythonw.exe" -I -m opensoul.launcher open
endlocal
