@echo off
setlocal enabledelayedexpansion

echo.
echo  ================================================
echo   LagLens v1.0 - Windows Build Script
echo  ================================================
echo.

REM ── Check Python ──────────────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found on PATH.
    echo         Install from https://python.org and tick "Add to PATH".
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo [OK] Found %%v

REM ── Check PyInstaller version (informational) ──────────────────────────────
pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] PyInstaller not yet installed - will install now.
) else (
    for /f "tokens=*" %%v in ('pyinstaller --version 2^>^&1') do (
        echo [OK] PyInstaller %%v
        echo      NOTE: hooksconfig PySide6 qt_modules requires version 5.8+.
        echo      If your version is older the spec already handles this safely.
    )
)

REM ── Check UPX (optional - build works fine without it) ────────────────────
upx --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] UPX not found - compression disabled ^(exe will be larger^).
    echo        Download from https://upx.github.io if you want smaller output.
    echo        The build will still complete successfully.
) else (
    for /f "tokens=1,2" %%a in ('upx --version 2^>^&1 ^| findstr /i "upx"') do (
        echo [OK] UPX found - you can enable upx=True in LagLens.spec for ~25%% smaller output.
    )
)

echo.

REM ── Install dependencies ───────────────────────────────────────────────────
echo [1/3] Installing dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 ( echo [ERROR] pip install failed & pause & exit /b 1 )

pip install pyinstaller --quiet
if errorlevel 1 ( echo [ERROR] PyInstaller install failed & pause & exit /b 1 )

echo       Done.
echo.

REM ── Ensure data folder exists ──────────────────────────────────────────────
if not exist "data" (
    mkdir data
    echo [INFO] Created 'data' folder ^(SQLite database will be stored here^).
)

REM ── Run PyInstaller ────────────────────────────────────────────────────────
echo [2/3] Building LagLens.exe...
echo       This takes 1-3 minutes. The window may look frozen - that is normal.
echo.

REM --noconfirm  overwrite dist\ without asking
REM --clean      delete the PyInstaller cache before building (avoids stale module errors)
REM No --log-level flag so warnings are visible in the console
pyinstaller LagLens.spec --noconfirm --clean

if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller build failed.
    echo.
    echo  Common causes:
    echo    - Missing dependency: run  pip install -r requirements.txt
    echo    - Antivirus blocking write to dist\: temporarily disable it
    echo    - PyInstaller too old: run  pip install --upgrade pyinstaller
    echo.
    echo  The full error should be visible above this line.
    pause & exit /b 1
)

REM ── Report result ──────────────────────────────────────────────────────────
echo.
echo [3/3] Build complete!
echo.
if exist "dist\LagLens.exe" (
    for %%F in (dist\LagLens.exe) do (
        set /a MB=%%~zF / 1048576
        echo   Output : dist\LagLens.exe
        echo   Size   : %%~zF bytes  ^(!MB! MB^)
    )
    echo.
    echo  NOTE: console=True in LagLens.spec — a terminal window will appear
    echo        when you run the exe. This is intentional for the first build
    echo        so you can see any error messages. Once it runs cleanly, set
    echo        console=False in LagLens.spec and rebuild.
) else (
    echo [WARNING] dist\LagLens.exe not found even though PyInstaller reported success.
    echo           Check the dist\ folder manually.
)

echo.
echo  To distribute: copy dist\LagLens.exe to any Windows machine.
echo  No Python installation required on the target machine.
echo.
pause
