from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_run_bat_compiles_audio_before_starting_python():
    startup_script = (PROJECT_ROOT / "run.bat").read_text(encoding="utf-8")

    compile_position = startup_script.index(
        'call "%PROJECT_ROOT%src\\audio\\compile_audio.bat"'
    )
    python_position = startup_script.index(
        '"%PROJECT_ROOT%.venv\\Scripts\\python.exe" -m src.main'
    )

    assert compile_position < python_position
    assert "if errorlevel 1" in startup_script


def test_compile_audio_bat_returns_compiler_status_without_pause():
    compile_script = (PROJECT_ROOT / "src" / "audio" / "compile_audio.bat").read_text(
        encoding="utf-8"
    )

    assert "pushd \"%~dp0\"" in compile_script
    assert "-static -static-libgcc -static-libstdc++" in compile_script
    assert "exit /b %COMPILE_EXIT_CODE%" in compile_script
    assert "pause" not in compile_script.lower()
