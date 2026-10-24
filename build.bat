@echo off
setlocal
cd /d "%~dp0"

call "%~dp0run.bat" --setup-only || exit /b 1
".venv\Scripts\python.exe" -m pip install pyinstaller==6.22.3 --disable-pip-version-check -q || goto :failed

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed ^
    --name Satsuma ^
    --icon assets\icon.ico ^
    --add-data "assets;assets" ^
    --collect-all pypdfium2 ^
    --collect-all pypdfium2_raw ^
    --collect-all pillow_heif ^
    main.py || goto :failed

if exist "dist\Satsuma.zip" del "dist\Satsuma.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\Satsuma' -DestinationPath 'dist\Satsuma.zip'"

echo.
echo  Built: dist\Satsuma\Satsuma.exe   (zipped: dist\Satsuma.zip)
echo  Keep the whole Satsuma folder together - the .exe needs the files beside it.
echo.
pause
exit /b 0

:failed
echo.
echo  Build failed - see the messages above.
pause
exit /b 1
