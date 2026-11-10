@echo off
setlocal enabledelayedexpansion
title Story Novel Crawler - Web Dashboard

echo ===================================================================
echo     CONG CU CAO TRUYEN DONG GOI ZIP (STORY-TRANSFER)
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
    echo [ERROR] Khong tim thay Python hop le tren may tinh nay!
    echo.
    echo Huong dan cai dat Python cho may moi:
    echo 1. Truy cap https://www.python.org/downloads/ va tai ban moi nhat.
    echo 2. Khi cai dat, NHO TICH CHON: "Add python.exe to PATH" (rat quan trong).
    echo 3. Sau khi cai dat xong, mo lai file Chay_Tool_Web.bat nay.
    echo.
    pause
    exit /b 1
)

echo [*] Su dung Python: "%PY_EXE%"

rem Kiem tra xem da cai thu vien chua, neu chua thi tu dong cai
"%PY_EXE%" -c "import uvicorn, fastapi, bs4, curl_cffi" >nul 2>nul
if !ERRORLEVEL! neq 0 (
    echo.
    echo [*] Phat hien may nay chua cai dat cac thu vien can thiet.
    echo [*] Dang tu dong cai dat thu vien tu requirements.txt, vui long cho 1-2 phut...
    echo.
    "%PY_EXE%" -m pip install -r requirements.txt
    if !ERRORLEVEL! neq 0 (
        echo.
        echo [ERROR] Cai dat thu vien that bai! Vui long kiem tra ket noi Internet.
        pause
        exit /b 1
    )
    echo.
    echo [*] Cai dat thu vien thanh cong!
    echo.
)

echo [*] Dang khoi dong Web Server tai http://localhost:8000 ...
echo [*] Trinh duyet se tu dong mo sau 2 giay.
echo.
echo (Nhan Ctrl+C tren cua so nay de tat ung dung khi xong)
echo ===================================================================

rem Open browser in background
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:8000"

rem Launch Uvicorn Web Server with auto-reload
"%PY_EXE%" -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload

pause
