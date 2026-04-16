import unittest
from unittest.mock import MagicMock, patch
from src.services.audio_service import AudioService

class TestAudio(unittest.TestCase):
    @patch("src.services.audio_service.sr.Recognizer")
    def setUp(self, mock_recognizer):
        self.mock_mic = MagicMock()
        # Inyectar micrófono mockeado para evitar fallos por hardware faltante
        self.audio = AudioService(microphone=self.mock_mic)

    def test_engine_lazy_load(self):
        # Audio engine no debe estar cargado al inicio
        self.assertIsNone(self.audio.engine)

    @patch("src.services.audio_service.pyttsx3.init")
    def test_engine_load_on_demand(self, mock_pyttsx3_init):
        mock_engine = MagicMock()
        mock_pyttsx3_init.return_value = mock_engine
        
        engine = self.audio.get_engine()
        self.assertIsNotNone(engine)
        self.assertEqual(engine, mock_engine)
        mock_pyttsx3_init.assert_called_once()
        
    def test_hablar_sin_texto(self):
        self.audio.hablar("") # No debe lanzar excepción
        
    def test_escuchar_sin_mic_usa_terminal(self):
        self.audio.microphone = None
        self.audio.recognizer = None
        
        with patch('builtins.input', return_value="comando consola"):
            res = self.audio.escuchar()
            self.assertEqual(res, "comando consola")

    def test_escuchar_unknown_value(self):
        import speech_recognition as sr
        self.audio.recognizer.recognize_google.side_effect = sr.UnknownValueError()
        res = self.audio.escuchar(timeout_silencio=0.1, limite_segundo=1)
        self.assertEqual(res, "")

    def test_escuchar_request_error(self):
        import speech_recognition as sr
        self.audio.recognizer.recognize_google.side_effect = sr.RequestError("API no disponible")
        res = self.audio.escuchar(timeout_silencio=0.1, limite_segundo=1)
        self.assertEqual(res, "")

if __name__ == "__main__":
    unittest.main()
