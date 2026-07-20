@echo off
setlocal
pushd "%~dp0"

where g++ >nul 2>&1
if errorlevel 1 (
    echo ERROR: No se encontro g++ en el PATH.
    popd
    exit /b 1
)

echo Compilando icaro_audio.cpp a icaro_audio.dll...
g++ -O3 -shared -static -static-libgcc -static-libstdc++ -o icaro_audio.dll icaro_audio.cpp -lole32 -lwinmm -lpropsys
if errorlevel 1 goto :compile_failed

echo Compilacion exitosa. icaro_audio.dll generado.
popd
exit /b 0

:compile_failed
set "COMPILE_EXIT_CODE=%ERRORLEVEL%"
echo Error de compilacion. codigo: %COMPILE_EXIT_CODE%
popd
exit /b %COMPILE_EXIT_CODE%
