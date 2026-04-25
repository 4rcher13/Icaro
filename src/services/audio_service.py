# audio_service.py
# Versión con calibración persistente y reintentos inteligentes

import os
import json
import time
import threading
import logging
import queue
from typing import Optional, Callable

import pyttsx3
import speech_recognition as sr

from ..config.settings import (
    VOICE_RATE,
    TIMEOUT_SILENCIO,
    LIMITE_SEGUNDOS,
    MIC_INDEX,
)

logger = logging.getLogger(__name__)

# Constantes
_POST_SPEECH_DELAY = 0.6
CALIBRATION_FILE = os.path.expanduser("~/.icaro_audio_config.json")
CALIBRATION_MAX_DAYS = 7          # Recalibrar después de 7 días
MAX_RETRIES = 3                    # Número máximo de reintentos
RETRY_BACKOFF = [0.5, 1.0, 2.0]   # Segundos de espera entre reintentos


class AudioService:
    """Maneja entrada (micrófono) y salida (voz) con calibración persistente y reintentos."""

    def __init__(self, microphone=None, on_feedback: Optional[Callable[[str], None]] = None):
        """
        Args:
            microphone: Instancia de micrófono (opcional).
            on_feedback: Callback para notificar al usuario (ej. para UI).
        """
        self.recognizer = None
        self.microphone = microphone
        self._mic_lock = threading.Lock()
        self._microphone_ready = False
        self.on_feedback = on_feedback  # Para notificaciones alternativas (UI)
        
        # Inicializar recognizer
        try:
            self.recognizer = sr.Recognizer()
            self.recognizer.dynamic_energy_threshold = False
            
            if os.getenv("FORCE_TERMINAL") == "true":
                logger.info("Modo FORCE_TERMINAL. Micrófono deshabilitado.")
                self.microphone = None
            elif self.microphone is None:
                logger.info(f"Usando micrófono índice: {MIC_INDEX}")
                self.microphone = sr.Microphone(device_index=MIC_INDEX)
        except Exception as exc:
            logger.error(f"Error inicializando audio: {exc}")
            self.microphone = None
        
        # Cargar calibración guardada (si existe y es reciente)
        self._load_calibration()
        
        # TTS worker (persistente)
        self._tts_queue: queue.Queue = queue.Queue()
        self._tts_worker_thread = threading.Thread(
            target=self._tts_worker, daemon=False, name="IcaroTTS"
        )
        self._tts_worker_thread.start()
    
    # ==================================================================
    # CALIBRACIÓN PERSISTENTE
    # ==================================================================
    
    def _load_calibration(self) -> None:
        """Carga el umbral calibrado desde archivo si es válido."""
        try:
            with open(CALIBRATION_FILE, "r") as f:
                data = json.load(f)
            
            # Verificar antigüedad
            timestamp = data.get("calibration_date", 0)
            edad_dias = (time.time() - timestamp) / 86400  # segundos a días
            
            if edad_dias > CALIBRATION_MAX_DAYS:
                logger.info(f"Calibración expirada (hace {edad_dias:.1f} días). Se recalibrará.")
                return
            
            # Verificar que el dispositivo no ha cambiado
            if data.get("mic_device_index") != MIC_INDEX:
                logger.info("Dispositivo de micrófono cambiado. Se recalibrará.")
                return
            
            # Cargar umbral
            self.recognizer.energy_threshold = data["energy_threshold"]
            self._microphone_ready = True
            logger.info(f"Calibración cargada: umbral = {self.recognizer.energy_threshold:.0f}")
            
        except FileNotFoundError:
            logger.info("No hay calibración previa. Se calibrará al primer uso.")
        except Exception as e:
            logger.warning(f"Error cargando calibración: {e}")
    
    def _save_calibration(self) -> None:
        """Guarda el umbral calibrado actual en disco."""
        if not self.recognizer:
            return
        
        data = {
            "energy_threshold": self.recognizer.energy_threshold,
            "calibration_date": time.time(),
            "mic_device_index": MIC_INDEX,
        }
        try:
            with open(CALIBRATION_FILE, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug("Calibración guardada correctamente.")
        except Exception as e:
            logger.warning(f"No se pudo guardar la calibración: {e}")
    
    def _setup_microphone(self) -> None:
        """Calibra el micrófono SOLO si es necesario (una vez, o si expiró)."""
        if self._microphone_ready:
            return  # Ya calibrado
        
        with self._mic_lock:
            if self._microphone_ready:
                return  # Double-check
            
            if not self.microphone or not self.recognizer:
                return
            
            try:
                with self.microphone as source:
                    logger.info("Calibrando micrófono (2 segundos en silencio)...")
                    self.recognizer.adjust_for_ambient_noise(source, duration=2.0)
                    
                    # Ajustar límites por seguridad
                    if self.recognizer.energy_threshold > 8000:
                        self.recognizer.energy_threshold = 8000
                    if self.recognizer.energy_threshold < 150:
                        self.recognizer.energy_threshold = 150
                    
                    logger.info(f"Calibración completada. Umbral: {self.recognizer.energy_threshold:.0f}")
                
                self._microphone_ready = True
                self._save_calibration()  # Guardar para futuras ejecuciones
                
            except Exception as exc:
                logger.error(f"Error calibrando micrófono: {exc}")
                self.microphone = None
    
    # ==================================================================
    # TTS WORKER (sin cambios relevantes)
    # ==================================================================
    
    def _tts_worker(self) -> None:
        """Hilo worker para síntesis de voz."""
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except ImportError:
            pass
            
        while True:
            try:
                item = self._tts_queue.get(timeout=0.5)
                if item is None:
                    break
                texto, evento = item
                evento.clear()
                
                engine = None
                try:
                    engine = pyttsx3.init()
                    voces = engine.getProperty("voices")
                    voz_es = next(
                        (v for v in (voces or []) if any(idioma in v.name.lower() for idioma in ("spanish", "sabina", "helena"))),
                        None,
                    )
                    if voz_es:
                        engine.setProperty("voice", voz_es.id)
                    elif voces:
                        engine.setProperty("voice", voces[0].id)
                    
                    engine.setProperty("rate", VOICE_RATE)
                    engine.setProperty("volume", 1.0)

                    engine.say(texto)
                    engine.runAndWait()
                except Exception as exc:
                    logger.error(f"Error reproduciendo TTS: {exc}")
                finally:
                    if engine:
                        engine.stop()
                    evento.set()
            except queue.Empty:
                continue
        
        try:
            import pythoncom
            pythoncom.CoUninitialize()
        except ImportError:
            pass
    
    def hablar(self, texto: str, post_delay: float = _POST_SPEECH_DELAY) -> None:
        """Sintetiza texto a voz."""
        if not texto:
            return
        texto_limpio = texto.replace("*", "").replace("#", "").replace("`", "").strip()
        if not texto_limpio:
            return
        
        logger.info(f"Ícaro dice: {texto_limpio}")
        evento = threading.Event()
        self._tts_queue.put((texto_limpio, evento))
        evento.wait(timeout=30)
        
        if post_delay > 0:
            time.sleep(post_delay)
    
    # ==================================================================
    # ESCUCHA CON REINTENTOS INTELIGENTES
    # ==================================================================
    
    def _notificar_usuario(self, mensaje: str) -> None:
        """Envía notificación al usuario (por TTS o callback)."""
        if self.on_feedback:
            self.on_feedback(mensaje)
        else:
            self.hablar(mensaje)
    
    def escuchar(
        self,
        timeout_silencio: Optional[float] = None,
        limite_segundos: Optional[int] = None,
        phrase_time_limit: int = 15,
    ) -> str:
        """
        Captura audio y lo reconoce con reintentos automáticos.
        Retorna el texto reconocido o cadena vacía si falla.
        """
        if timeout_silencio is None:
            timeout_silencio = TIMEOUT_SILENCIO
        if limite_segundos is None:
            limite_segundos = LIMITE_SEGUNDOS
        
        # Asegurar que el micrófono está calibrado
        self._setup_microphone()
        
        if not self.microphone or not self.recognizer:
            logger.warning("No hay micrófono disponible")
            return ""
        
        for intento in range(MAX_RETRIES):
            try:
                with self.microphone as source:
                    logger.debug(f"Escuchando... (intento {intento + 1}/{MAX_RETRIES})")
                    self.recognizer.pause_threshold = timeout_silencio
                    
                    audio = self.recognizer.listen(
                        source,
                        timeout=limite_segundos,
                        phrase_time_limit=phrase_time_limit,
                    )
                    
                    # Intentar reconocer con Google
                    comando = self.recognizer.recognize_google(audio, language="es-ES")
                    comando = comando.lower().strip()
                    logger.info(f"Usuario dijo: '{comando}'")
                    return comando
            
            except sr.WaitTimeoutError:
                # Silencio total -> el usuario no habló
                logger.debug("Silencio total, no se reintenta.")
                return ""
            
            except sr.UnknownValueError:
                # No se entendió el audio (ruido, susurro, etc.)
                if intento < MAX_RETRIES - 1:
                    espera = RETRY_BACKOFF[intento]
                    logger.debug(f"No entendí (intento {intento + 1}/{MAX_RETRIES}). Reintentando en {espera}s...")
                    time.sleep(espera)
                else:
                    logger.warning("No se pudo entender después de varios intentos.")
                    self._notificar_usuario("No he podido entender lo que dijiste, intenta de nuevo.")
                    return ""
            
            except sr.RequestError as exc:
                # Error de red / API de Google
                logger.error(f"Error de conexión con Google: {exc}")
                if intento < MAX_RETRIES - 1:
                    espera = RETRY_BACKOFF[intento]
                    logger.debug(f"Reintentando en {espera}s...")
                    time.sleep(espera)
                else:
                    self._notificar_usuario("Tengo problemas de conexión, verifica tu internet.")
                    return ""
            
            except Exception as exc:
                # Cualquier otro error inesperado
                logger.error(f"Error inesperado en escucha: {exc}")
                if intento < MAX_RETRIES - 1:
                    espera = RETRY_BACKOFF[intento]
                    time.sleep(espera)
                else:
                    return ""
        
        return ""
    
    def shutdown(self) -> None:
        """Detiene el TTS worker y libera recursos."""
        self._tts_queue.put(None)
        if self._tts_worker_thread.is_alive():
            self._tts_worker_thread.join(timeout=5)
            logger.info("TTS worker detenido")