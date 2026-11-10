@echo off
setlocal enabledelayedexpansion
title Story Novel Crawler - Cai Dat Thu Vien

echo ===================================================================
echo     CAI DAT MOI TRUONG VA THU VIEN CHO TOOL CRAWLER
echo ===================================================================
echo.

rem Check Python path
set "PY_EXE="
if exist "C:\laragon\bin\python\python-3.13\python.exe" (
    set "PY_EXE=C:\laragon\bin\python\python-3.13\python.exe"
    goto :FoundPython
)

where python >nul 2>nul
if %ERRORLEVEL% equ 0 (
    python -c "import sys; sys.exit(0)" >nul 2>nul
    if !ERRORLEVEL! equ 0 (
        set "PY_EXE=python"
        goto :FoundPython
    )
)

where py >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "PY_EXE=py"
    goto :FoundPython
)

if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" (
    set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    goto :FoundPython
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    goto :FoundPython
)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto :FoundPython
)
if exist "%PROGRAMFILES%\Python313\python.exe" (
    set "PY_EXE=%PROGRAMFILES%\Python313\python.exe"
    goto :FoundPython
)
if exist "%PROGRAMFILES%\Python312\python.exe" (
    set "PY_EXE=%PROGRAMFILES%\Python312\python.exe"
    goto :FoundPython
)

:FoundPython
if "%PY_EXE%"=="" (
    echo [ERROR] Khong tim thay Python tren may tinh nay!
    echo.
    echo Huong dan:
    echo 1. Vao https://www.python.org/downloads/ de tai Python.
    echo 2. Khi cai, NHO TICH CHON o vuong: "Add python.exe to PATH".
    echo 3. Mo lai file nay sau khi cai xong Python.
    echo.
    pause
    exit /b 1
)

echo [*] Da tim thay Python: "%PY_EXE%"
echo [*] Dang tien hanh cai dat cac goi thu vien tu requirements.txt...
echo.

"%PY_EXE%" -m pip install --upgrade pip
"%PY_EXE%" -m pip install -r requirements.txt

if %ERRORLEVEL% equ 0 (
    echo.
    echo ===================================================================
    echo [SUCCESS] DA CAI DAT XONG TOAN BO THU VIEN!
    echo Bay gio ban co the nhap dup chuot vao "Chay_Tool_Web.bat" de su dung.
    echo ===================================================================
) else (
    echo.
    echo [ERROR] Cai dat that bai, vui long kiem tra lai ket noi mang.
)

pause
