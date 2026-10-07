@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Aplikasi belum diinstal. Jalankan INSTAL_WINDOWS.bat terlebih dahulu.
  pause
  exit /b 1
)
if not exist .env (
  echo Konfigurasi belum ada. Jalankan INSTAL_WINDOWS.bat terlebih dahulu.
  pause
  exit /b 1
)
start "" http://localhost:8000
.venv\Scripts\python.exe start.py
pause
