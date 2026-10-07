@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo =========================================
echo     INSTALASI SANJARA HADIR
 echo =========================================
where py >nul 2>&1
if %errorlevel% neq 0 (
  echo Python belum ditemukan. Instal Python 3.11+ dahulu dari python.org
  pause
  exit /b 1
)
if not exist .venv (
  py -m venv .venv
  if %errorlevel% neq 0 goto failed
)
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
if %errorlevel% neq 0 goto failed
if not exist .env (
  python -m scripts.setup
  if %errorlevel% neq 0 goto failed
)
echo.
echo Instalasi siap. Alamat aplikasi: http://localhost:8000
start "" http://localhost:8000
python start.py
goto end
:failed
echo Instalasi gagal. Periksa jaringan dan Python, lalu ulangi.
pause
exit /b 1
:end
pause
