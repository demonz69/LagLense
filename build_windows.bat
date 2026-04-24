@echo off
setlocal

echo.
echo  ================================================
echo   LagLens v1.0 - Windows Build Script
echo  ================================================
echo.

REM --- Check Python is installed ---
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install from https://python.org
    pause & exit /b 1
)

REM --- Check / install pip dependencies ---
echo [1/3] Installing dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 ( echo [ERROR] pip install failed & pause & exit /b 1 )

pip install pyinstaller --quiet
if errorlevel 1 ( echo [ERROR] pyinstaller install failed & pause & exit /b 1 )

REM --- Make sure data folder exists (SQLite will create the .db inside it) ---
if not exist "data" mkdir data

REM --- Build the exe ---
echo [2/3] Building LagLens.exe ...
pyinstaller LagLens.spec --noconfirm --clean
if errorlevel 1 ( echo [ERROR] PyInstaller build failed & pause & exit /b 1 )

echo [3/3] Done!
echo.
echo  Output: dist\LagLens.exe
echo  Size:
for %%F in (dist\LagLens.exe) do echo    %%~zF bytes
echo.
echo  You can now run dist\LagLens.exe directly - no Python needed.
echo  To share it, just copy that single .exe file.
echo.
pause
