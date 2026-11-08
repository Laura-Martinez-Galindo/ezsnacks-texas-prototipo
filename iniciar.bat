@echo off
REM Doble clic para abrir EzSnack Impuestos en el navegador (Windows)
cd /d "%~dp0"
set PY=
where py >nul 2>nul && set PY=py
if not defined PY where python >nul 2>nul && set PY=python
if not defined PY (
  echo No se encontro Python en este computador.
  echo Instale Python 3.11 o superior desde la pagina que se va a abrir
  echo ^(marque "Add Python to PATH"^) y vuelva a abrir este archivo.
  start https://www.python.org/downloads/windows/
  pause
  exit /b 1
)
if not exist .venv (
  echo Instalando por primera vez, espere unos minutos...
  %PY% -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt
)
echo Abriendo EzSnack Impuestos en http://localhost:8501 ...
.venv\Scripts\python -m streamlit run app.py --server.port 8501
pause
