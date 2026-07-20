from pathlib import Path


CPP_PATH = Path(__file__).resolve().parents[1] / "src" / "audio" / "icaro_audio.cpp"


def test_wasapi_silent_packets_are_converted_to_zero_samples():
    source = CPP_PATH.read_text(encoding="utf-8")

    assert "AUDCLNT_BUFFERFLAGS_SILENT" in source
    assert "resampler.Process(nullptr, numFramesAvailable, targetSamples)" in source


def test_discontinuities_reset_resampler_state():
    source = CPP_PATH.read_text(encoding="utf-8")

    assert "resampler.Reset()" in source


def test_wasapi_uses_callers_audio_timeouts():
    source = (Path(__file__).resolve().parents[1] / "src" / "services" / "audio_service.py").read_text(
        encoding="utf-8"
    )

    assert "def escuchar_wasapi(self, timeout_silencio: float, limite_segundos: int)" in source
    assert "return self.escuchar_wasapi(ts, ls)" in source


def test_capture_does_not_blindly_use_stereo_mix_as_microphone():
    source = CPP_PATH.read_text(encoding="utf-8")

    assert "SelectCaptureDevice" in source
    assert "ICARO_AUDIO_DEVICE" in source
    assert "stereo mix" in source
    assert "mezcla estéreo" in source


def test_native_bridge_exposes_selected_device_for_diagnostics():
    source = CPP_PATH.read_text(encoding="utf-8")

    assert "IcaroAudio_GetDeviceName" in source
    assert "_dll.IcaroAudio_GetDeviceName" in (
        Path(__file__).resolve().parents[1] / "src" / "services" / "audio_service.py"
    ).read_text(encoding="utf-8")


def test_pcm_conversion_uses_the_declared_sample_width():
    source = CPP_PATH.read_text(encoding="utf-8")

    assert "pwfx->wBitsPerSample" in source
    assert "bits_per_sample_" in source
    assert "bits_per_sample_ == 24" in source
