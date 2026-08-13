@echo off
rem Double-click this. It sets Crossfoot up the first time and opens the window
rem every time after, so nobody has to learn a terminal to look at their own
rem receipts.
rem
rem Deliberately a visible script rather than a compiled binary: this program
rem reads your bank statements, and a file you can open in Notepad is a better
rem trust proposition than an unsigned .exe that Windows will warn you about.
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  echo Setting up Crossfoot. This happens once and takes a minute.
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 (
    echo.
    echo Python is not installed. Get it from https://python.org/downloads
    echo and tick "Add Python to PATH" during the install, then run this again.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -e ".[ui]"
)

echo Opening Crossfoot in your browser. Close this window to stop it.
".venv\Scripts\python.exe" -m crossfoot.cli
pause
