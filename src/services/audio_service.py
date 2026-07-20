import os
import time
import threading
import logging
import queue
import collections
import ctypes
from pathlib import Path
from typing import Optional, Callable

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False

# Ctypes Structs y Enums para icaro_audio.dll
class AudioStats(ctypes.Structure):
    _fields_ = [
        ("droppedFrames", ctypes.c_int),
        ("overruns", ctypes.c_int),
        ("underruns", ctypes.c_int),
        ("latencyMs", ctypes.c_float),
        ("bufferUsage", ctypes.c_float),
        ("sampleRate", ctypes.c_int)
    ]

# Resultados de Inicialización
AUDIO_INIT_OK = 0
AUDIO_INIT_DEVICE_NOT_FOUND = 1
AUDIO_INIT_ACCESS_DENIED = 2
AUDIO_INIT_UNSUPPORTED_FORMAT = 3
AUDIO_INIT_FAILED = 4

# Resultados de Lectura
AUDIO_READ_OK = 0
AUDIO_READ_TIMEOUT = 1
AUDIO_READ_STOPPED = 2
AUDIO_READ_ERROR = 3

_DLL_PATH = Path(__file__).resolve().parent.parent / "audio" / "icaro_audio.dll"
_dll = None
DLL_AVAILABLE = False

if os.path.exists(_DLL_PATH):
    try:
        _dll = ctypes.CDLL(str(_DLL_PATH))
        _dll.IcaroAudio_Start.argtypes = []
        _dll.IcaroAudio_Start.restype = ctypes.c_int
        
        _dll.IcaroAudio_Stop.argtypes = []
        _dll.IcaroAudio_Stop.restype = None
        
        _dll.IcaroAudio_Read.argtypes = [
            ctypes.POINTER(ctypes.c_int16),
            ctypes.c_int,
            ctypes.c_int
        ]
        _dll.IcaroAudio_Read.restype = ctypes.c_int
        
        _dll.IcaroAudio_GetStats.argtypes = [ctypes.POINTER(AudioStats)]
        _dll.IcaroAudio_GetStats.restype = None

        if hasattr(_dll, "IcaroAudio_GetDeviceName"):
            _dll.IcaroAudio_GetDeviceName.argtypes = []
            _dll.IcaroAudio_GetDeviceName.restype = ctypes.c_wchar_p
        
        DLL_AVAILABLE = True
        logging.info("icaro_audio.dll cargado con éxito. WASAPI activo.")
    except Exception as e:
        logging.warning(f"No se pudo cargar icaro_audio.dll: {e}. Fallback a sounddevice.")
else:
    logging.info("icaro_audio.dll no encontrado. Se usará el backend de Python.")

import pyttsx3
import speech_recognition as sr
import webrtcvad

try:
    import sounddevice as sd
    SD_AVAILABLE = True
except ImportError:
    SD_AVAILABLE = False
    logging.warning("sounddevice no está instalado. VAD Real desactivado.")

try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False
    logging.warning("gTTS no está instalado. Fallback a pyttsx3 activo.")

from ..config.settings import (
    VOICE_RATE,
    TIMEOUT_SILENCIO,
    LIMITE_SEGUNDOS,
    MIC_INDEX,
    AUDIO_RATE,
    VAD_AGGRESSIVENESS,
)

logger = logging.getLogger(__name__)

# B4 FIX: ruta absoluta calculada una vez, independiente del cwd del proceso
_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_TTS_TEMP_PATH = str(_DATA_DIR / "tts_temp.mp3")

def play_mp3_winmm(filepath: str) -> bool:
    """Reproduce un archivo MP3 en Windows usando MCI (winmm.dll) esperando a que termine."""
    import platform
    if platform.system() != "Windows":
        return False
    try:
        import ctypes
        import os
        if not os.path.exists(filepath):
            return False
        path_clean = os.path.abspath(filepath).replace('\\', '/')
        winmm = ctypes.windll.winmm
        winmm.mciSendStringW("close mymp3", None, 0, 0)
        res_open = winmm.mciSendStringW(f'open "{path_clean}" type mpegvideo alias mymp3', None, 0, 0)
        if res_open != 0:
            return False
        res_play = winmm.mciSendStringW("play mymp3 wait", None, 0, 0)
        winmm.mciSendStringW("close mymp3", None, 0, 0)
        return res_play == 0
    except Exception as e:
        logger.error(f"Error en play_mp3_winmm: {e}")
        return False

_POST_SPEECH_DELAY = 0.15

class AudioService:
    """Maneja entrada (micrófono) y salida (voz) optimizado con WebRTC VAD y sounddevice."""

    def __init__(self, microphone=None, on_feedback: Optional[Callable[[str], None]] = None):
        self.recognizer = sr.Recognizer()
        self.microphone = microphone
        self.on_feedback = on_feedback
        
        self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS) if SD_AVAILABLE else None
        
        # Inicializar Silero VAD si la DLL de captura está disponible
        self.silero_vad = None
        if DLL_AVAILABLE:
            try:
                from .silero_vad import SileroVAD
                self.silero_vad = SileroVAD()
            except Exception as e:
                logging.warning(f"No se pudo inicializar Silero VAD: {e}. Desactivando DLL.")
        
        # TTS worker
        self._tts_queue: queue.Queue = queue.Queue()
        self._tts_worker_thread = threading.Thread(
            target=self._tts_worker, daemon=True, name="IcaroTTS"
        )
        self._tts_worker_thread.start()

    def _find_voice_id(self) -> Optional[str]:
        """Busca la voz en español UNA sola vez."""
        try:
            engine = pyttsx3.init()
            voces = engine.getProperty("voices")
            voz_es = next(
                (v for v in (voces or []) if any(
                    idioma in v.name.lower() for idioma in ("spanish", "sabina", "helena")
                )), None
            )
            voice_id = voz_es.id if voz_es else (voces[0].id if voces else None)
            engine.stop()
            return voice_id
        except Exception as exc:
            logger.error(f"Error buscando voz TTS: {exc}")
            return None

    def _tts_worker(self) -> None:
        """Worker asíncrono para TTS con Google TTS y fallback offline pyttsx3."""
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except ImportError:
            pass

        # Buscamos el voice_id UNA sola vez (esto es lo que demoraba 2s).
        voice_id = None
        try:
            voice_id = self._find_voice_id()
        except Exception:
            pass

        # B4 FIX: usar ruta absoluta precalculada a nivel de módulo
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        temp_audio_path = _TTS_TEMP_PATH

        engine = None
        while True:
            try:
                item = self._tts_queue.get(timeout=0.5)
                if item is None:
                    break
                texto, evento = item
                evento.clear()
                
                gtts_success = False
                if GTTS_AVAILABLE:
                    try:
                        logger.debug(f"Generando Google TTS para: {texto}")
                        tts = gTTS(text=texto, lang="es", slow=False)
                        
                        # Limpiar archivo anterior si existe
                        if os.path.exists(temp_audio_path):
                            try:
                                os.remove(temp_audio_path)
                            except Exception:
                                pass
                                
                        tts.save(temp_audio_path)
                        # Reproducir con MCI winmm
                        if play_mp3_winmm(temp_audio_path):
                            gtts_success = True
                    except Exception as e:
                        logger.warning(f"Google TTS falló, usando fallback offline pyttsx3: {e}")
                
                if not gtts_success:
                    # Inicializar el engine pyttsx3 justo antes de hablar (fallback)
                    engine = None
                    try:
                        engine = pyttsx3.init()
                        if voice_id:
                            engine.setProperty("voice", voice_id)
                        engine.setProperty("rate", VOICE_RATE)
                        engine.setProperty("volume", 1.0)
                        
                        engine.say(texto)
                        engine.runAndWait()
                    except Exception as exc:
                        logger.error(f"Error reproduciendo con pyttsx3: {exc}")
                    finally:
                        if engine:
                            try:
                                engine.stop()
                            except Exception:
                                pass
                evento.set()
            except queue.Empty:
                continue

        # Limpieza final
        if engine:
            try:
                engine.stop()
            except Exception:
                pass
        # Eliminar archivo temporal al apagar
        if os.path.exists(temp_audio_path):
            try:
                os.remove(temp_audio_path)
            except Exception:
                pass
        try:
            import pythoncom
            pythoncom.CoUninitialize()
        except ImportError:
            pass

    def hablar(self, texto: str, post_delay: float = _POST_SPEECH_DELAY) -> None:
        """Sintetiza texto a voz usando el queue."""
        if not texto:
            return
        texto_limpio = texto.replace("*", "").replace("#", "").replace("`", "").strip()
        if not texto_limpio:
            return
        
        logger.info(f"Ícaro: {texto_limpio}")
        
        # B13 FIX: dividir por cualquier separador de oración o salto de línea
        # Soporta tanto ". " como ".\n" y variantes mixtas
        import re
        frases = [f.strip() for f in re.split(r'(?<=[.!?])\s+|\n+', texto_limpio) if f.strip()]
        
        for frase in frases:
            evento = threading.Event()
            self._tts_queue.put((frase, evento))
            # Tiempo máximo de espera por cada frase
            evento.wait(timeout=30)
        

        if post_delay > 0:
            time.sleep(post_delay)

    def _notificar_usuario(self, mensaje: str) -> None:
        if self.on_feedback:
            self.on_feedback(mensaje)
        else:
            self.hablar(mensaje)

    def escuchar_vad(self) -> str:
        """
        Escucha usando WebRTC VAD y sounddevice para latencia cero al finalizar.
        """
        frame_duration_ms = 30
        frame_size = int(AUDIO_RATE * (frame_duration_ms / 1000.0))
        
        q = queue.Queue()
        
        def audio_callback(indata, frames, time_info, status):
            # indata es float32 [-1.0, 1.0]. webrtcvad necesita int16 bytes.
            # numpy se importa al nivel del módulo, no aquí (evita overhead por frame)
            if _NUMPY_AVAILABLE:
                audio_data = (indata[:, 0] * 32767).astype(np.int16).tobytes()
            else:
                import array
                samples = [int(s * 32767) for s in indata[:, 0]]
                audio_data = array.array('h', samples).tobytes()
            q.put(audio_data)

        # Buffer para guardar el audio útil
        audio_buffer = []
        triggered = False
        silence_frames = 0
        # Tolerancia: X frames de silencio = cortar escucha
        MAX_SILENCE_FRAMES = int(TIMEOUT_SILENCIO * 1000 / frame_duration_ms) 
        
        logger.debug("Escuchando (VAD Real)...")
        
        try:
            with sd.InputStream(samplerate=AUDIO_RATE, channels=1, dtype='float32', blocksize=frame_size, callback=audio_callback):
                start_time = time.time()
                
                while True:
                    if time.time() - start_time > LIMITE_SEGUNDOS:
                        logger.debug("Timeout de grabación alcanzado.")
                        break
                        
                    frame = q.get()
                    
                    try:
                        is_speech = self.vad.is_speech(frame, AUDIO_RATE)
                    except Exception as e:
                        logger.error(f"VAD Error: {e}")
                        is_speech = False

                    if not triggered:
                        if is_speech:
                            triggered = True
                            audio_buffer.append(frame)
                            logger.debug("Voz detectada.")
                    else:
                        audio_buffer.append(frame)
                        if not is_speech:
                            silence_frames += 1
                            if silence_frames > MAX_SILENCE_FRAMES:
                                logger.debug("Fin de voz detectado.")
                                break
                        else:
                            silence_frames = 0

            if not audio_buffer:
                return ""

            # Reconstruir audio completo
            raw_audio = b''.join(audio_buffer)
            
            # Pasar a speech_recognition
            audio_data = sr.AudioData(raw_audio, AUDIO_RATE, 2) # 2 bytes = 16 bit
            
            comando = self.recognizer.recognize_google(audio_data, language="es-ES")
            comando = comando.lower().strip()
            logger.info(f"Usuario: '{comando}'")
            return comando

        except sr.UnknownValueError:
            return ""
        except Exception as e:
            logger.error(f"Error en VAD escuchar: {e}")
            return ""

    def escuchar_legacy(self, timeout_silencio=TIMEOUT_SILENCIO, limite_segundos=LIMITE_SEGUNDOS) -> str:
        """Fallback a speech_recognition tradicional si VAD/sounddevice falla."""
        try:
            if self.microphone is None:
                self.microphone = sr.Microphone(device_index=MIC_INDEX)

            with self.microphone as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                self.recognizer.pause_threshold = timeout_silencio
                audio = self.recognizer.listen(source, timeout=limite_segundos, phrase_time_limit=15)
                comando = self.recognizer.recognize_google(audio, language="es-ES")
                return comando.lower().strip()
        except Exception:
            return ""

    def escuchar_wasapi(self, timeout_silencio: float, limite_segundos: int) -> str:
        """
        Escucha utilizando WASAPI (C++ DLL) y Silero VAD ONNX.
        Consumo de CPU de ~0% en reposo gracias al bloqueo de la DLL liberando el GIL.
        """
        if not DLL_AVAILABLE or self.silero_vad is None:
            return ""
            
        logger.debug("Escuchando con backend WASAPI + Silero VAD...")
        
        # Iniciar captura nativa en C++
        init_res = _dll.IcaroAudio_Start()
        if init_res != AUDIO_INIT_OK:
            error_msgs = {
                AUDIO_INIT_DEVICE_NOT_FOUND: "Dispositivo de entrada de audio no encontrado.",
                AUDIO_INIT_ACCESS_DENIED: "Permiso de acceso al micrófono denegado.",
                AUDIO_INIT_UNSUPPORTED_FORMAT: "Formato de audio del sistema no soportado por el resampler.",
                AUDIO_INIT_FAILED: "Error general al inicializar WASAPI."
            }
            err_msg = error_msgs.get(init_res, f"Error desconocido: {init_res}")
            logger.error(f"Fallo al iniciar WASAPI: {err_msg}")
            self._notificar_usuario(f"Error de audio: {err_msg}")
            return ""

        device_name = (
            _dll.IcaroAudio_GetDeviceName()
            if hasattr(_dll, "IcaroAudio_GetDeviceName")
            else "unknown"
        )
        logger.info(
            "WASAPI iniciado: dispositivo=%r pid=%s hilo=%s",
            device_name,
            os.getpid(),
            threading.get_ident(),
        )
            
        self.silero_vad.reset()
        
        # Frame size de 1536 muestras (96ms a 16kHz)
        frame_size = 1536
        read_buffer = (ctypes.c_int16 * frame_size)()
        
        # Pre-buffer de 500ms para no recortar la 'I' de 'Icaro'
        # 500ms a 16000Hz = 8000 muestras. 5 frames de 1536 = 7680 muestras (480ms).
        pre_buffer_frames = collections.deque(maxlen=5)
        
        triggered = False
        speech_frames = []
        silence_frames_count = 0
        
        frame_duration_sec = frame_size / AUDIO_RATE
        max_silence_frames = int(timeout_silencio / frame_duration_sec)
        max_total_frames = int(limite_segundos / frame_duration_sec)
        total_frames_count = 0
        consecutive_timeouts = 0
        captured_samples = 0
        nonzero_samples = 0
        peak_sample = 0
        sum_squares = 0.0
        
        try:
            while True:
                # Leer desde la DLL. Bloquea hasta 1000ms.
                # Al liberar el GIL, Python no consume CPU durante la espera.
                read_res = _dll.IcaroAudio_Read(read_buffer, frame_size, 1000)
                
                if read_res == AUDIO_READ_STOPPED:
                    logger.debug("Captura de audio detenida.")
                    break
                elif read_res == AUDIO_READ_TIMEOUT:
                    consecutive_timeouts += 1
                    logger.warning("Timeout leyendo de la DLL WASAPI.")
                    if consecutive_timeouts >= 3:
                        logger.error("Demasiados timeouts consecutivos. Abortando escucha.")
                        break
                    continue
                elif read_res == AUDIO_READ_ERROR:
                    logger.error("Error de lectura en WASAPI.")
                    break
                    
                consecutive_timeouts = 0
                frame_np = np.frombuffer(read_buffer, dtype=np.int16).copy()
                captured_samples += frame_np.size
                nonzero_samples += int(np.count_nonzero(frame_np))
                peak_sample = max(peak_sample, int(np.max(np.abs(frame_np))))
                sum_squares += float(np.dot(frame_np.astype(np.float32), frame_np))
                
                # Obtener probabilidad de habla
                prob = self.silero_vad.is_speech(frame_np)
                
                if not triggered:
                    if prob > 0.5:
                        triggered = True
                        for f in pre_buffer_frames:
                            speech_frames.append(f)
                        speech_frames.append(frame_np)
                        logger.debug("Voz activa detectada por Silero VAD.")
                    else:
                        pre_buffer_frames.append(frame_np)
                else:
                    speech_frames.append(frame_np)
                    if prob < 0.35: # Histéresis
                        silence_frames_count += 1
                        if silence_frames_count > max_silence_frames:
                            logger.debug("Fin de voz detectado por Silero VAD.")
                            break
                    else:
                        silence_frames_count = 0
                        
                total_frames_count += 1
                if total_frames_count > max_total_frames:
                    logger.debug("Límite de tiempo alcanzado.")
                    break
                    
            # Detener captura y liberar recursos en C++
            _dll.IcaroAudio_Stop()
            
            # Obtener y mostrar estadísticas de audio para diagnóstico
            stats = AudioStats()
            _dll.IcaroAudio_GetStats(ctypes.byref(stats))
            logger.debug(
                f"AudioStats -> Pérdidas: {stats.droppedFrames}, Sobrecargas: {stats.overruns}, "
                f"Subcargas: {stats.underruns}, Latencia: {stats.latencyMs:.1f}ms, "
                f"Uso Buffer: {stats.bufferUsage:.1f}%, Frames: {total_frames_count}, "
                f"Muestras: {captured_samples}, NoCero: {nonzero_samples}, "
                f"RMS: {(sum_squares / captured_samples) ** 0.5 if captured_samples else 0.0:.1f}, "
                f"Peak: {peak_sample}"
            )
            
            if not speech_frames:
                return ""
                
            # Reconstruir audio completo
            raw_audio = b''.join(f.tobytes() for f in speech_frames)
            audio_data = sr.AudioData(raw_audio, AUDIO_RATE, 2)
            
            comando = self.recognizer.recognize_google(audio_data, language="es-ES")
            comando = comando.lower().strip()
            logger.info(f"Usuario (WASAPI): '{comando}'")
            return comando
            
        except sr.UnknownValueError:
            return ""
        except Exception as e:
            logger.error(f"Error en bucle de escucha WASAPI: {e}")
            return ""
        finally:
            if _dll:
                _dll.IcaroAudio_Stop()

    def escuchar(
        self,
        timeout_silencio: Optional[float] = None,
        limite_segundos: Optional[int] = None,
        phrase_time_limit: int = 15,
        **kwargs,
    ) -> str:
        # Compatibilidad con tests/código antiguo que usaba limite_segundo
        if limite_segundos is None and "limite_segundo" in kwargs:
            limite_segundos = kwargs["limite_segundo"]
        ts = timeout_silencio if timeout_silencio is not None else TIMEOUT_SILENCIO
        ls = limite_segundos if limite_segundos is not None else LIMITE_SEGUNDOS
        
        # 1. Backend optimizado: WASAPI (C++ DLL) + Silero VAD
        #    Si la DLL está disponible, se usa en exclusiva para evitar
        #    abrir el micrófono desde dos backends al mismo tiempo.
        if DLL_AVAILABLE and self.silero_vad is not None:
            return self.escuchar_wasapi(ts, ls)
                
        # 2. Fallback a WebRTC VAD + sounddevice
        if SD_AVAILABLE and self.vad:
            return self.escuchar_vad()
            
        # 3. Fallback final a speech_recognition legacy
        return self.escuchar_legacy(timeout_silencio=ts, limite_segundos=ls)
    
    def shutdown(self) -> None:
        """Detiene el TTS worker, la captura WASAPI y libera recursos."""
        # 1. Detener captura de audio nativa (desbloquea cualquier Read() pendiente)
        if DLL_AVAILABLE and _dll:
            try:
                _dll.IcaroAudio_Stop()
            except Exception as e:
                logger.warning(f"Error al detener IcaroAudio: {e}")
        # 2. Detener TTS worker
        self._tts_queue.put(None)
        if self._tts_worker_thread.is_alive():
            self._tts_worker_thread.join(timeout=5)
            logger.info("TTS worker detenido")
