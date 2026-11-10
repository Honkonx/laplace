@echo off
setlocal
chcp 65001 >nul
rem Instalador de Laplace para Windows. Opciones: instalar.bat -SinAsistente ^| -Reconfigurar ^| -ConNode ^| -ConML ^| -Rehacer
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install\windows\instalar.ps1" %*
set "CODIGO=%ERRORLEVEL%"
rem Con doble clic la ventana se cierra sola al terminar y no deja leer nada: se espera una tecla.
rem Desde una terminal ya abierta no molesta; LAPLACE_SIN_PAUSA=1 lo desactiva (scripts y pruebas).
if defined LAPLACE_SIN_PAUSA exit /b %CODIGO%
echo %cmdcmdline% | "%SystemRoot%\System32\find.exe" /i "%~nx0" >nul && (echo. & pause)
exit /b %CODIGO%
