@echo off
chcp 65001 >nul
title Installazione Sottomano
cd /d "%~dp0"

rem Registro di cio' che installa Sottomano: la disinstallazione rimuove SOLO quello.
set "SM=%LOCALAPPDATA%\Sottomano"
if not exist "%SM%" mkdir "%SM%"
set "REG=%SM%\installato.txt"

echo.
echo === 1/2  Programmi necessari (tramite winget, l'installer ufficiale di Windows) ===
where winget >nul 2>nul || (echo winget non trovato: aggiorna "Programma di installazione app" dal Microsoft Store. & pause & exit /b 1)
call :programma Python.Python.3.12 "Python 3.12" --scope user
call :programma 7zip.7zip "7-Zip"
call :programma UB-Mannheim.TesseractOCR "Tesseract OCR"

set "PY="
rem Uso sempre Python 3.12: e' quello che installa.bat garantisce, con tutte le librerie
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY for /f "delims=" %%p in ('py -3.12 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%p"
if not defined PY (echo Python non trovato: chiudi questa finestra e rilancia installa.bat. & pause & exit /b 1)

echo.
echo === 2/2  Configurazione di Sottomano ===
"%PY%" "%~dp0installa.py"
pause
exit /b

:programma
winget list --id %1 -e --accept-source-agreements >nul 2>nul && (echo   %~2 gia' presente: non lo tocco& exit /b)
echo   Installo %~2...
winget install --id %1 -e --accept-package-agreements --accept-source-agreements %3 %4
rem lo segno nel registro solo se l'ha installato davvero Sottomano
winget list --id %1 -e --accept-source-agreements >nul 2>nul && >>"%REG%" echo winget %1
exit /b
