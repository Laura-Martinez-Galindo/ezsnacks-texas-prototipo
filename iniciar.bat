@echo off
REM Doble clic para abrir EzSnack Impuestos en el navegador (Windows)
cd /d "%~dp0"
if not exist .venv (
  echo Instalando por primera vez, espere unos minutos...
  py -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
.venv\Scripts\python -m streamlit run app.py
