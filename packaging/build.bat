@echo off
rem Build Bar None for Windows.
rem Double-click this file, or run it from a terminal at the repo root:
rem     packaging\build.bat
setlocal
rem pushd (not cd) so a UNC path like \\wsl.localhost\... gets mapped to a
rem temp drive letter — plain `cd /d` fails there and lands in C:\Windows.
pushd "%~dp0.."
if errorlevel 1 (
    echo ERROR: cannot reach the project folder: %~dp0..
    pause
    exit /b 1
)

echo === Building Bar None ===

rem Running from the WSL filesystem (\\wsl.localhost\...) works but is very
rem slow — Windows Python does every venv/pip/PyInstaller file op over the
rem network mount. Prefer a copy under C:\Users\... if this crawls.
set "HERE=%~dp0"
if "%HERE:~0,2%"=="\\" echo NOTE: project is on a UNC/WSL path - the build may be slow.

if not exist .venv\Scripts\activate.bat (
    echo Creating virtual environment...
    py -3 -m venv .venv 2>nul || python -m venv .venv
)
if not exist .venv\Scripts\activate.bat (
    echo ERROR: could not create .venv - is Python 3 installed?
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat

echo Installing requirements...
python -m pip install -r requirements.txt -r requirements-dev.txt
if errorlevel 1 (
    echo ERROR: dependency install failed.
    pause
    exit /b 1
)

echo Running PyInstaller...
pyinstaller packaging\barnone.spec --noconfirm --clean
if errorlevel 1 (
    echo ERROR: build failed.
    pause
    exit /b 1
)

echo.
echo Done!
echo   App:   dist\BarNone\BarNone.exe
echo   Share: zip the whole dist\BarNone folder
pause
