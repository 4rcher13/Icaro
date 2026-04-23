import pyttsx3 #Convertir texto a voz
import speech_recognition as sr
import time
import logging
from ..utils.text_utils import normalize_text

from ..config.settings import VOICE_RATE, TIMEOUT_SILENCIO, LIMITE_SEGUNDOS, MIC_INDEX

logger = logging.getLogger(__name__)

# Tiempo de silencio posterior al TTS para que el micrófono no capture el eco
_POST_SPEECH_DELAY = 0.6




class AudioService:
    """Maneja entrada (micrófono) y salida (voz) de Ícaro."""

    def __init__(self, microphone=None):
        self.engine = None
        self.recognizer = None
        self.microphone = microphone
        self.ultima_interaccion = time.time()
        self._microphone_ready = False

        try:
            import os
            self.recognizer = sr.Recognizer()
            # Umbral dinámico: el reconocedor ajusta el nivel de energía en tiempo real
            self.recognizer.dynamic_energy_threshold = True

            if os.getenv("FORCE_TERMINAL") == "true":
                logger.info("Modo FORCE_TERMINAL. Evitando micrófono.")
                self.microphone = None
            elif self.microphone is None:
                logger.info(f"Usando micrófono índice: {MIC_INDEX}")
                self.microphone = sr.Microphone(device_index=MIC_INDEX)
        except Exception as exc:
            logger.error(f"Error inicializando audio: {exc}")
            self.microphone = None

    # ------------------------------------------------------------------
    # Calibración (se ejecuta solo una vez, al primer escuchar())
    # ------------------------------------------------------------------

    def _setup_microphone(self) -> None:
        if self._microphone_ready or not self.microphone or not self.recognizer:
            return
        try:
            with self.microphone as source:
                logger.info("Calibrando micrófono (2 s)... no hables todavía.")
                self.recognizer.adjust_for_ambient_noise(source, duration=2.0)

                # Si el umbral queda muy alto, puede no detectar voz normal
                if self.recognizer.energy_threshold > 400:
                    logger.warning(
                        f"Umbral de ruido muy alto "
                        f"({self.recognizer.energy_threshold:.0f}), limitando a 350."
                    )
                    self.recognizer.energy_threshold = 350

                logger.info(
                    f"Calibración completa. "
                    f"Umbral de energía: {self.recognizer.energy_threshold:.0f}"
                )
            self._microphone_ready = True
        except Exception as exc:
            logger.error(f"Error calibrando micrófono: {exc}")
            self.microphone = None

    # ------------------------------------------------------------------
    # Motor TTS (lazy init, con reintento)
    # ------------------------------------------------------------------

    def get_engine(self):
        """Carga pyttsx3 la primera vez que se necesita."""
        if self.engine is None:
            try:
                self.engine = pyttsx3.init()
                voces = self.engine.getProperty("voices")

                # Priorizar voz en español
                voz_es = next(
                    (
                        v for v in (voces or [])
                        if "spanish" in v.name.lower()
                        or "es" in v.id.lower()
                        or "sabina" in v.name.lower()
                        or "helena" in v.name.lower()
                    ),
                    None,
                )
                if voz_es:
                    self.engine.setProperty("voice", voz_es.id)
                    logger.info(f"Voz TTS (ES): {voz_es.name}")
                elif voces:
                    self.engine.setProperty("voice", voces[0].id)
                    logger.info(f"Voz TTS (fallback): {voces[0].name}")

                self.engine.setProperty("rate", VOICE_RATE)
            except Exception as exc:
                logger.error(f"Error iniciando motor TTS: {exc}")
                self.engine = None
        return self.engine

    # ------------------------------------------------------------------
    # Hablar
    # ------------------------------------------------------------------

    def hablar(self, texto: str) -> None:
        """Sintetiza texto a voz y espera hasta terminar."""
        if not texto:
            return

        texto_limpio = (
            texto.replace("*", "").replace("#", "").replace("`", "").strip()
        )
        if not texto_limpio:
            return

        logger.info(f"Ícaro dice: {texto_limpio}")

        engine = self.get_engine()
        if not engine:
            logger.error("Motor TTS no disponible.")
            return

        try:
            engine.say(texto_limpio)
            engine.runAndWait()
        except Exception as exc:
            logger.error(f"Error TTS: {exc}. Reiniciando motor...")
            self.engine = None  # Forzar re-inicio en el siguiente hablar()
            # Segundo intento con motor fresco
            try:
                engine = self.get_engine()
                if engine:
                    engine.say(texto_limpio)
                    engine.runAndWait()
            except Exception as exc2:
                logger.error(f"Error TTS (segundo intento): {exc2}")
        finally:
            # ──── Pausa anti-eco ────────────────────────────────────
            # Evita que el micrófono capture el sonido que acaba de
            # emitir el altavoz y lo procese como un nuevo comando.
            time.sleep(_POST_SPEECH_DELAY)

    # ------------------------------------------------------------------
    # Escuchar
    # ------------------------------------------------------------------

    def escuchar(
        self,
        timeout_silencio: float = None,
        limite_segundo: int = None,
    ) -> str:
        """Captura audio del micrófono y lo convierte a texto (es-ES)."""
        if timeout_silencio is None:
            timeout_silencio = TIMEOUT_SILENCIO
        if limite_segundo is None:
            limite_segundo = LIMITE_SEGUNDOS

        self._setup_microphone()

        if not self.microphone or not self.recognizer:
            return input("\n[Tú]: ").strip().lower()

        with self.microphone as source:
            try:
                self.recognizer.pause_threshold = timeout_silencio
                audio = self.recognizer.listen(
                    source,
                    timeout=limite_segundo,
                    phrase_time_limit=15,
                )
                comando = self.recognizer.recognize_google(audio, language="es-ES")
                comando = comando.lower().strip()
                logger.info(f"Usuario dijo: '{comando}'")
                return comando

            except sr.WaitTimeoutError:
                pass  # Silencio durante todo el timeout → normal
            except sr.UnknownValueError:
                logger.debug("Audio no reconocido (ruido o voz muy baja).")
            except sr.RequestError as exc:
                logger.error(f"Error Google STT (¿sin internet?): {exc}")
            except Exception as exc:
                logger.error(f"Error en escucha: {exc}")

        return ""
