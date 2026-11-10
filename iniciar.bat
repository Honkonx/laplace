@echo off
setlocal
chcp 65001 >nul
rem Iniciar Laplace: avisa si falta algo clave, enciende el backend y el agente, y abre la web. Opciones: --lan ^| --sin-agente
set "RAIZ=%~dp0"
set "PY="
for %%R in ("runtime\venv" ".venv" ".venv_backend") do if not defined PY if exist "%RAIZ%%%~R\Scripts\python.exe" set "PY=%RAIZ%%%~R\Scripts\python.exe"
if not defined PY (
  echo Laplace no esta instalado en esta carpeta: ejecuta instalar.bat primero.
  call :esperar
  exit /b 1
)
"%PY%" "%RAIZ%install\comun\laplace.py" iniciar --avisar --abrir %*
set "CODIGO=%ERRORLEVEL%"
call :esperar
exit /b %CODIGO%

:esperar
rem Con doble clic la ventana se cierra sola al terminar y no deja leer nada: se espera una tecla.
rem Desde una terminal ya abierta no molesta; LAPLACE_SIN_PAUSA=1 lo desactiva (scripts y pruebas).
if defined LAPLACE_SIN_PAUSA exit /b 0
echo %cmdcmdline% | "%SystemRoot%\System32\find.exe" /i "%~nx0" >nul && (echo. & pause)
exit /b 0
