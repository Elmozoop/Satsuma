@echo off
setlocal
cd /d "%~dp0"

rem Builds dist\Satsuma.exe: one file people can download and double-click. No Python needed.

call "%~dp0run.bat" --setup-only || exit /b 1
".venv\Scripts\python.exe" -m pip install pyinstaller==6.22.3 --disable-pip-version-check -q || goto :failed

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onefile ^
    --name Satsuma ^
    --icon assets\icon.ico ^
    --add-data "assets;assets" ^
    --collect-all pypdfium2 ^
    --collect-all pypdfium2_raw ^
    --collect-all pillow_heif ^
    main.py || goto :failed

rem Packaging can quietly drop a plugin or DLL: let the exe check every engine itself.
echo.
echo  Checking the built exe...
"dist\Satsuma.exe" --self-test --report="dist\selftest.txt"
set "RESULT=%ERRORLEVEL%"
type "dist\selftest.txt"
if not "%RESULT%"=="0" (
    echo.
    echo  The self-test found a problem - see the FAIL lines above.
    pause
    exit /b 1
)

echo.
echo  Built: dist\Satsuma.exe
echo  That one file is all anyone needs: download it and double-click.
echo.
pause
exit /b 0

:failed
echo.
echo  Build failed - see the messages above.
pause
exit /b 1
