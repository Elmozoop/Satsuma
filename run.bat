@echo off
setlocal
cd /d "%~dp0"

rem ---- find Python (the py launcher first, then python on PATH) -------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto :nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul || goto :nopython

rem ---- private virtual environment with the requirements ---------------------
rem installed.ok holds a copy of requirements.txt: when an update changes the list, install again.
set "SETUP="
if not exist ".venv\installed.ok" set "SETUP=1"
if not defined SETUP fc /b requirements.txt ".venv\installed.ok" >nul 2>nul || set "SETUP=1"
if defined SETUP (
    echo Setting up Satsuma. This takes a minute or two...
    if not exist ".venv\Scripts\python.exe" (
        %PY% -m venv .venv || goto :failed
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip --disable-pip-version-check -q
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check || goto :failed
    copy /y requirements.txt ".venv\installed.ok" >nul
)

if /i "%~1"=="--setup-only" exit /b 0
start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py" %*
exit /b 0

:nopython
echo.
echo  Satsuma needs Python 3.10 or newer.
echo  Get it from https://www.python.org/downloads/
echo  and tick "Add python.exe to PATH" in the installer, then run this again.
echo.
pause
exit /b 1

:failed
echo.
echo  Installing Satsuma's requirements failed - see the messages above.
echo  Check your internet connection and run this file again.
echo.
pause
exit /b 1
