@echo off
setlocal enabledelayedexpansion

:: ============================================
::  Auto Use - Windows Dev Setup
:: ============================================
::  Creates venv, installs pip deps, installs the Interception kernel
::  driver, and reboots. Platform-shared files (main.py, cli.py,
::  frontend/index.html, frontend/script.js) detect the OS at runtime,
::  so no file patching is needed — one checkout runs on both macOS
::  and Windows as-is.

:: --- 1. Admin self-elevation ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Requesting Administrator privileges...
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

:: --- 2. Anchor to script location ---
cd /d "%~dp0"

echo.
echo ============================================
echo   Auto Use - Windows Setup
echo ============================================
echo.

:: --- 3. Sanity-check repo layout ---
:: Required: main.py, windows_requirements.txt, Interception installer.
:: Optional (proprietary): Auto_Use\windows_use - skipped if absent.
set "MISSING="
if not exist "main.py" set "MISSING=main.py"
if not exist "windows_requirements.txt" set "MISSING=windows_requirements.txt"
if not exist "Interception\command line installer\install-interception.exe" set "MISSING=Interception\command line installer\install-interception.exe"

if defined MISSING (
    echo [ERROR] Required file not found: %MISSING%
    echo.
    echo Are you running this from the repo root? Expected layout:
    echo   ^<repo^>\main.py
    echo   ^<repo^>\windows_requirements.txt
    echo   ^<repo^>\Interception\command line installer\install-interception.exe
    echo.
    pause
    exit /b 1
)

:: Optional proprietary pieces - informational only, not fatal.
if not exist "Auto_Use\windows_use"     echo [i] Auto_Use\windows_use not found - proprietary module absent.

:: --- 4. Python check ---
echo [*] Checking for Python...

set "PYTHON_EXE="
set "PYLINE="

:: 4a. First try 'python' on PATH, but reject the Microsoft Store stub.
set "STUB="
for /f "usebackq delims=" %%p in (`where python 2^>nul`) do (
    echo %%p | findstr /i "WindowsApps" >nul && set "STUB=1" || set "PYTHON_EXE=%%p"
)

:: 4b. If nothing usable on PATH, search standard install locations.
if not defined PYTHON_EXE (
    for %%D in (
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "C:\Program Files\Python313\python.exe"
        "C:\Program Files\Python312\python.exe"
        "C:\Program Files\Python311\python.exe"
        "C:\Program Files\Python310\python.exe"
    ) do (
        if not defined PYTHON_EXE (
            if exist %%D set "PYTHON_EXE=%%~D"
        )
    )
)

:: 4c. Validate whichever python.exe we found.
if defined PYTHON_EXE (
    for /f "usebackq delims=" %%v in (`""!PYTHON_EXE!" --version" 2^>^&1`) do set "PYLINE=%%v"
    echo !PYLINE! | findstr /b /c:"Python 3" >nul || set "PYTHON_EXE="
)

if not defined PYTHON_EXE (
    echo.
    echo ============================================
    echo   [ERROR] Python is not installed
    echo ============================================
    echo.
    echo   I searched PATH and the standard install folders
    echo   and could not find a working Python 3.x.
    echo.
    if defined STUB echo   ^(Ignored the Microsoft Store stub - it's not real Python.^)
    echo.
    echo   No worries - I'll grab Python 3.13.3 for you.
    echo.
    echo ============================================
    echo   Here's what's about to happen:
    echo ============================================
    echo.
    echo   [i] In a few seconds I'll download:
    echo         python-3.13.3-amd64.exe
    echo       to your Downloads folder.
    echo.
    echo   Then please do this:
    echo     1^) Run the installer from Downloads.
    echo     2^) Click "Install Now" and wait until it finishes.
    echo     3^) Close this window, open a NEW terminal,
    echo        and re-run: windows_setup.bat
    echo.
    echo ################################################
    echo #                                              #
    echo #   !!  CRITICAL - DO NOT SKIP THIS STEP  !!   #
    echo #                                              #
    echo #   On the FIRST screen of the installer,      #
    echo #   at the BOTTOM, you MUST check the box:     #
    echo #                                              #
    echo #       [x] Add python.exe to PATH             #
    echo #                                              #
    echo #   If you miss this checkbox, NOTHING will    #
    echo #   work and you'll be stuck in a loop.        #
    echo #   CHECK IT before clicking "Install Now".    #
    echo #                                              #
    echo ################################################
    echo.
    echo   I'm waiting for you. Come back when it's done! :^)
    echo.
    echo   Starting download in 10 seconds...
    echo.

    for /l %%i in (10,-1,1) do (
        <nul set /p "=  Downloading in %%i... "
        timeout /t 1 /nobreak >nul
        echo.
    )

    start "" "https://www.python.org/ftp/python/3.13.3/python-3.13.3-amd64.exe"

    echo.
    echo   [OK] Download triggered. Check your Downloads folder.
    echo.
    echo   REMINDER: Check "Add python.exe to PATH" on the
    echo             first screen of the installer. :^)
    echo.
    pause
    exit /b 1
)

echo [OK] Found %PYLINE%
echo [OK] Using: %PYTHON_EXE%

:: --- 5. venv ---
echo.
if exist "venv\Scripts\python.exe" (
    echo [OK] Reusing existing venv\
) else (
    echo [*] Creating venv...
    "%PYTHON_EXE%" -m venv venv
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create venv
        pause
        exit /b 1
    )
    if not exist "venv\Scripts\python.exe" (
        echo [ERROR] venv\Scripts\python.exe was not created.
        echo         Your Python install is incomplete or is the Microsoft Store stub.
        echo         Reinstall Python 3.13.3 from: https://www.python.org/downloads/release/python-3133/
        pause
        exit /b 1
    )
    echo [OK] venv created
)

:: --- 6. pip install ---
echo.
echo [*] Upgrading pip...
"venv\Scripts\python.exe" -m pip install --upgrade pip
if %errorlevel% neq 0 (
    echo [ERROR] pip upgrade failed
    pause
    exit /b 1
)

echo.
echo [*] Installing requirements from windows_requirements.txt ...
"venv\Scripts\python.exe" -m pip install -r windows_requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Dependency installation failed. Fix the error above and re-run.
    pause
    exit /b 1
)
echo [OK] Requirements installed

:: --- 7. Install Interception driver ---
echo.
echo ============================================
echo   Installing Interception Driver
echo ============================================
echo.

set "INSTALLER=%~dp0Interception\command line installer\install-interception.exe"
echo [*] Running: "%INSTALLER%" /install
"%INSTALLER%" /install
set INSTALL_RC=%errorlevel%

echo.
if %INSTALL_RC% equ 0 (
    echo [OK] Interception driver installed
) else (
    echo [!] Installer returned code: %INSTALL_RC%
    echo     The driver may not be fully registered. Reboot and check anyway.
)

:: --- 8. Verification (informational) ---
echo.
echo [*] Verifying driver registration...
powershell -NoProfile -Command "$val = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4D36E96B-E325-11CE-BFC1-08002BE10312}' -Name UpperFilters -ErrorAction SilentlyContinue).UpperFilters; if ($val -match 'interception') { Write-Host '  [OK] Keyboard filter registered' } else { Write-Host '  [--] Keyboard filter NOT registered yet' }"
powershell -NoProfile -Command "$val = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4D36E96F-E325-11CE-BFC1-08002BE10312}' -Name UpperFilters -ErrorAction SilentlyContinue).UpperFilters; if ($val -match 'interception') { Write-Host '  [OK] Mouse filter registered' } else { Write-Host '  [--] Mouse filter NOT registered yet' }"

:: --- 9. Reboot ---
echo.
echo ============================================
echo   Setup complete
echo ============================================
echo.
echo [!] The Interception driver requires a REBOOT to activate.
echo [!] The system will reboot in 30 seconds.
echo [!] To cancel: open cmd and run:  shutdown /a
echo.
shutdown /r /t 30 /c "Auto Use setup complete - rebooting to activate Interception driver."

endlocal
