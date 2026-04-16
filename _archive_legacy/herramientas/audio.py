"""
herramientas/audio.py — Módulo de Audio de Ícaro
Controla: Micrófono (STT), Voz (TTS) y señales UDP al widget visual.
"""

import time
import queue
import socket
import unicodedata

try:
    import pyttsx3
    import speech_recognition as sr
    import sounddevice as sd
    import numpy as np
except ImportError as e:
    print(f"[ERROR] Dependencia de audio faltante: {e.name}")
    print("Instala con: pip install pyttsx3 SpeechRecognition sounddevice numpy")
    raise SystemExit(1)


class AudioManager:
    """Gestiona toda la entrada/salida de audio del asistente."""

    def __init__(self):
        # --- Voz TTS (español) ---
        print("[Audio] Inicializando motor de voz...")
        self.engine = pyttsx3.init()
        self.voice_id = self._inicializar_voz_espanol(self.engine)
        if self.voice_id:
            self.engine.setProperty('voice', self.voice_id)
        self.engine.setProperty('rate', 185) # Un poco más rápido para naturalidad

        # --- Micrófono ---
        print("[Audio] Optimizando dispositivo de entrada...")
        self.mic_index, self.mic_rate = self._detectar_microfono()
        if self.mic_index is None:
            print("[WARN] No se detectó micrófono. El asistente estará en modo sordo.")
            self.mic_rate = 44100 # Default fallback
        else:
            print(f"[OK] Microfono activo (Dispositivo {self.mic_index})")

        # --- Recognizer STT ---
        self.recognizer = sr.Recognizer()

        # --- Socket UDP para el Widget visual ---
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp_dest = ("127.0.0.1", 5005)

        # --- Marca de tiempo de última interacción ---
        self.ultima_interaccion = 0.0

    # ===================== INICIALIZACIÓN =====================

    @staticmethod
    def _inicializar_voz_espanol(engine):
        """Detecta la voz en español disponible."""
        voice_id = None
        try:
            for voice in engine.getProperty('voices'):
                if "spanish" in voice.name.lower() or "es" in voice.id.lower():
                    voice_id = voice.id
                    break
        except Exception:
            pass
        return voice_id

    @staticmethod
    def _detectar_microfono():
        """Busca e inicializa el micrófono de forma casi instantánea usando los valores por defecto del kernel."""
        try:
            device_idx = sd.default.device[0]
            if device_idx is None:
                return None, None
            
            info = sd.query_devices(device_idx)
            rate = int(info["default_samplerate"])
            # Si tiene entradas, lo retornamos directo sin iterar bloqueando el hilo
            if info["max_input_channels"] > 0:
                return device_idx, rate
        except Exception:
            pass
            
        print("[WARN] Falló detección rápida. Intentando bypass...")
        return None, None

    # ===================== COMUNICACIÓN UI =====================

    def cambiar_estado_ui(self, estado):
        """Envío UDP non-blocking al Widget visual."""
        try:
            self._sock.sendto(estado.encode(), self._udp_dest)
        except Exception:
            pass

    # ===================== HABLAR (TTS) =====================

    def hablar(self, texto):
        """Muestra en terminal y reproduce TTS usando el motor persistente."""
        print(f"Asistente: {texto}")
        self.ultima_interaccion = time.time()
        self.cambiar_estado_ui("speaking")
        try:
            self.engine.say(texto)
            self.engine.runAndWait()
        except Exception as e:
            print(f"[ERR TTS] {e}")
            # Reintentar inicialización si el motor muere
            self.engine = pyttsx3.init()
            if self.voice_id: self.engine.setProperty('voice', self.voice_id)
            self.engine.say(texto)
            self.engine.runAndWait()

    # ===================== ESCUCHAR (STT) =====================

    def escuchar(self, timeout_silencio=2.0, limite_segundo=12):
        """
        Escucha el micrófono evaluando ruido en tiempo real.
        Umbral dinámico de 1.5x sobre el piso de ruido.
        """
        chunk_size = int(self.mic_rate * 0.25)
        frames = []
        hablando = False
        silencio_acumulado = 0.0
        q = queue.Queue()

        def cb_audio(indata, fr, tiempo, status):
            q.put(indata.copy())

        try:
            with sd.InputStream(samplerate=self.mic_rate, channels=1, dtype='int16',
                                device=self.mic_index, callback=cb_audio, blocksize=chunk_size):

                # Auto-calibrar ruido ambiental (1 segundo = 4 chunks de 250ms)
                fondo = [max(np.max(np.abs(q.get())), 10) for _ in range(4)]
                umbral_ruido = max(np.mean(fondo) * 1.5, 150)

                # Grabar evaluando volumen por chunk
                for _ in range(int(limite_segundo / 0.25)):
                    try:
                        chunk = q.get(timeout=1.0)
                    except queue.Empty:
                        break

                    if np.max(np.abs(chunk)) > umbral_ruido:
                        hablando = True
                        silencio_acumulado = 0.0
                    elif hablando:
                        silencio_acumulado += 0.25

                    frames.append(chunk)

                    if hablando and silencio_acumulado >= timeout_silencio:
                        break

            # STT via Google
            if frames and hablando:
                audio_np = np.concatenate(frames, axis=0)
                audio_data = sr.AudioData(audio_np.tobytes(), self.mic_rate, 2)
                raw = self.recognizer.recognize_google(audio_data, language="es-MX").lower()
                comando = unicodedata.normalize('NFKD', raw).encode('ASCII', 'ignore').decode()
                print(f"[INFO] Dijiste: {comando} (Original: {raw})")
                return comando

        except sr.UnknownValueError:
            return ""
        except sr.RequestError:
            self.hablar("Mi conexión a internet parece fallar o es lenta.")
            time.sleep(2)
        except Exception as e:
            print(f"[ERROR de Captura] {e}")
            time.sleep(2)

        return ""
