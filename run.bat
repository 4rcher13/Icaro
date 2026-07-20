@echo off
setlocal
set "PROJECT_ROOT=%~dp0"
set "PYTHONPATH=%PROJECT_ROOT%."

:: ── Compilar el backend nativo de audio antes de iniciar Python ───
call "%PROJECT_ROOT%src\audio\compile_audio.bat"
if errorlevel 1 (
    echo.
    echo ERROR: No se pudo compilar el servicio nativo de audio.
    echo El asistente no se iniciara porque icaro_audio.dll no esta disponible.
    pause
    exit /b 1
)

:: Descomenta la siguiente linea si quieres forzar el modo terminal (sin micrófono)
:: set FORCE_TERMINAL=true

:: ── Lanzar widget UI en segundo plano (sin consola) ──────────────
start "" "%PROJECT_ROOT%.venv\Scripts\pythonw.exe" "%PROJECT_ROOT%ui\widget.py"

:: Pequeña pausa para que la UI arranque antes que el asistente
timeout /t 1 /nobreak > nul

:: ── Lanzar asistente principal ───────────────────────────────────
"%PROJECT_ROOT%.venv\Scripts\python.exe" -m src.main

pause
