import pyttsx3
import speech_recognition as sr
import time
import logging

from ..config.settings import VOICE_RATE, TIMEOUT_SILENCIO, LIMITE_SEGUNDOS

logger = logging.getLogger(__name__)

class AudioService:
    """Maneja la entrada (micrófono) y salida (voz) de Ícaro de forma limpia."""

    def __init__(self, microphone=None):
        self.engine = None
        self.recognizer = None
        self.microphone = microphone
        self.ultima_interaccion = time.time()
        self._microphone_ready = False
        
        try:
            self.recognizer = sr.Recognizer()
            if self.microphone is None:
                self.microphone = sr.Microphone()
        except Exception as e:
            logger.error(f"Error inicializando componentes base de audio: {e}")
            self.microphone = None

    def _setup_microphone(self):
        if self._microphone_ready or not self.microphone or not self.recognizer:
            return
            
        try:
            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=1.0)
            self._microphone_ready = True
        except Exception as e:
            logger.error(f"Error calibrando ruido del micrófono: {e}")
            self.microphone = None

    def get_engine(self):
        """Lazy load del motor TTS para acelerar el inicio."""
        if self.engine is None:
            try:
                self.engine = pyttsx3.init()
                voces = self.engine.getProperty('voices')
                if voces:
                    self.engine.setProperty('voice', voces[0].id)
                self.engine.setProperty('rate', VOICE_RATE)
            except Exception as e:
                logger.error(f"Error arrancando motor TTS: {e}")
                self.engine = None
        return self.engine

    def hablar(self, texto: str):
        """Sintetiza texto a voz."""
        if not texto: return
        logger.info(f"Ícaro dice: {texto}")
        
        engine = self.get_engine()
        if not engine:
            return
            
        texto_limpio = texto.replace("*", "").replace("#", "").replace("`", "").strip()
        
        try:
            engine.say(texto_limpio)
            engine.runAndWait()
        except Exception as e:
            logger.error(f"Error al intentar hablar: {e}")

    def escuchar(self, timeout_silencio: float = None, limite_segundo: int = None) -> str:
        """Escucha el micrófono y lo convierte a texto de forma síncrona."""
        if timeout_silencio is None: timeout_silencio = TIMEOUT_SILENCIO
        if limite_segundo is None: limite_segundo = LIMITE_SEGUNDOS
        
        self._setup_microphone()
        
        if not self.microphone or not self.recognizer:
            # Fallback a terminal si no hay mic
            return input("\n[Escribe comando de emergencia] Tú: ").strip().lower()

        with self.microphone as source:
            try:
                self.recognizer.pause_threshold = timeout_silencio
                audio = self.recognizer.listen(source, timeout=limite_segundo, phrase_time_limit=15)
                
                comando = self.recognizer.recognize_google(audio, language="es-ES")
                comando = comando.lower().strip()
                logger.info(f"Usuario dijo: {comando}")
                return comando

            except sr.WaitTimeoutError:
                pass 
            except sr.UnknownValueError:
                pass 
            except sr.RequestError as e:
                logger.error(f"Error SR: {e}")
            except Exception as e:
                logger.error(f"Error genérico en escucha: {e}")
        return ""
