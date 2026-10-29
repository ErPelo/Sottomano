@echo off
chcp 65001 >nul
title Disinstallazione Sottomano
set "DOPO=%TEMP%\sottomano_dopo.txt"
if exist "%DOPO%" del "%DOPO%"

set "PY="
rem Uso sempre Python 3.12: e' quello che installa.bat garantisce, con tutte le librerie
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY for /f "delims=" %%p in ('py -3.12 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%p"
if not defined PY (echo Python non trovato. & pause & exit /b 1)

"%PY%" "%~dp0disinstalla.py"
if errorlevel 1 (pause & exit /b)

rem Programmi installati da Sottomano (e cartella di Python, se era sua): ora che Python e' chiuso
if exist "%DOPO%" (
    for /f "usebackq tokens=1,*" %%a in ("%DOPO%") do (
        if "%%a"=="winget" (
            echo Disinstallo %%b...
            winget uninstall --id %%b -e --silent --accept-source-agreements
        )
        if "%%a"=="cartella" if exist "%%b" rmdir /s /q "%%b"
    )
    del "%DOPO%"
)
echo.
echo Fatto. Sottomano e quello che aveva installato sono stati rimossi.
pause
if /i "%~dp0"=="%LOCALAPPDATA%\Sottomano\" (cd /d "%TEMP%" & (goto) 2>nul & rmdir /s /q "%LOCALAPPDATA%\Sottomano")
