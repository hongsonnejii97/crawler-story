@echo off
setlocal enabledelayedexpansion
title Story Novel Crawler - CLI

echo ===================================================================
echo     CONG CU CAO TRUYEN XUAT FILE WORD - CLI RUNNER
echo ===================================================================
echo.

rem 1. Check Laragon Python path
set "PY_EXE="
if exist "C:\laragon\bin\python\python-3.13\python.exe" (
    set "PY_EXE=C:\laragon\bin\python\python-3.13\python.exe"
    goto :FoundPython
)

rem 2. Check standard python.exe
where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python -c "import sys; sys.exit(0)" >nul 2>nul
    if !ERRORLEVEL! equ 0 (
        set "PY_EXE=python"
        goto :FoundPython
    )
)

rem 3. Check py launcher
where py >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "PY_EXE=py"
    goto :FoundPython
)

rem 4. Search common installation paths
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    goto :FoundPython
)
if exist "%PROGRAMFILES%\Python313\python.exe" (
    set "PY_EXE=%PROGRAMFILES%\Python313\python.exe"
    goto :FoundPython
)

:FoundPython
if "%PY_EXE%"=="" (
    echo [ERROR] Khong tim thay Python hop le tren may tinh!
    pause
    exit /b 1
)

echo [*] Su dung Python: "%PY_EXE%"
echo.

"%PY_EXE%" cli.py %*

if %ERRORLEVEL% neq 0 (
    echo.
    pause
)
