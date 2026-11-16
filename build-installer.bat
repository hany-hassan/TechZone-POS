@echo off
rem TechZone full release builder: builds dist\TechZone.exe + Inno Setup dist\TechZone-Setup-v<ver>.exe
cd /d "%~dp0"
setlocal
set "APP_VERSION=2.0.0"
if not "%~1"=="" set "APP_VERSION=%~1"

where python >nul 2>nul || (echo [ERROR] python not found & pause & exit /b 1)
python -c "import PyInstaller" 2>nul || python -m pip install pyinstaller
python -c "import webview" 2>nul || python -m pip install pywebview

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [1/3] Building dist\TechZone.exe via PyInstaller...
python -m PyInstaller --noconfirm --clean --name TechZone --windowed --onefile --icon "icon.ico" --add-data "web;web" --add-data "icon.ico;." app\main.py || (echo [ERROR] PyInstaller build failed & pause & exit /b 1)

set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC (
  for /f "delims=" %%I in ('where ISCC 2^>nul') do set "ISCC=%%I"
)
if not defined ISCC (
  echo [ERROR] Inno Setup 6 ^(ISCC.exe^) not found. Install Inno Setup 6 and retry.
  pause
  exit /b 1
)

echo [2/3] Compiling Inno Setup installer (v%APP_VERSION%)...
"%ISCC%" "/DMyAppVersion=%APP_VERSION%" "installer\TechZone.iss" || (echo [ERROR] Inno Setup compile failed & pause & exit /b 1)

echo [3/3] Generating SHA-256 checksums for GitHub Releases...
powershell -NoProfile -Command "Get-ChildItem 'dist\TechZone*.exe' | ForEach-Object { $h = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(); \"$h  $($_.Name)\" } | Set-Content -Encoding UTF8 'dist\SHA256SUMS.txt'"

echo.
echo Setup Ready: "%~dp0dist\TechZone-Setup-v%APP_VERSION%.exe"
echo Checksums  : "%~dp0dist\SHA256SUMS.txt"
pause
