"""
Configuración del asistente Ícaro.
Carga variables de entorno, define rutas y parámetros con validaciones.
"""

import os
import sys
from pathlib import Path
from typing import Set, Optional, Final
from dotenv import load_dotenv

# ----------------------------------------------------------------------
# Carga de variables de entorno
# ----------------------------------------------------------------------
load_dotenv()

# ----------------------------------------------------------------------
# Rutas base (absolutas)
# ----------------------------------------------------------------------
BASE_DIR: Final[Path] = Path(__file__).resolve().parent.parent
DATA_DIR: Final[Path] = BASE_DIR / "data"
LOGS_DIR: Final[Path] = BASE_DIR / "logs"

# Asegurar que los directorios existen
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# ----------------------------------------------------------------------
# Seguridad y API keys
# ----------------------------------------------------------------------
GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY no está definida en el entorno o archivo .env")
    sys.exit(1)  # Falla rápido y con mensaje claro

# ----------------------------------------------------------------------
# Palabras de activación (evitar falsos positivos)
# ----------------------------------------------------------------------
# Se elimina "y" por ser demasiado corta y común.
WAKE_WORD: Set[str] = {"ícaro", "icaro", "hícaro", "e caro", "y claro", "y creo", "y caro"}

# ----------------------------------------------------------------------
# Modelos de IA
# ----------------------------------------------------------------------
MODELO_LOCAL: str = os.getenv("MODELO_OLLAMA", "qwen2.5:3b")  # permite override vía entorno
# Verificación opcional (se puede hacer en tiempo de ejecución)
# Por ahora solo se asigna un valor por defecto configurable.

# ----------------------------------------------------------------------
# Microfono: índice (None = predeterminado)
# ----------------------------------------------------------------------
MIC_INDEX: Optional[int] = None  # Cambiar a entero si se necesita un mic específico

# ----------------------------------------------------------------------
# Historial de conversación
# ----------------------------------------------------------------------
MAX_HISTORY: Final[int] = 40
HISTORY_FILE: Final[Path] = DATA_DIR / "historial.json"

# ----------------------------------------------------------------------
# Audio y síntesis de voz
# ----------------------------------------------------------------------
VOICE_RATE: int = 130  # Velocidad de voz (dependiente del motor usado)
# Nota: si usas pyttsx3, el rango típico es 100-200; 130 es conversacional.

# ----------------------------------------------------------------------
# Parámetros de captura de voz (VAD + grabación)
# ----------------------------------------------------------------------
AUDIO_RATE: Final[int] = 16000
AUDIO_CHANNELS: Final[int] = 1
AUDIO_FRAME_DURATION_MS: Final[int] = 20
AUDIO_FRAME_SIZE: Final[int] = int(AUDIO_RATE * AUDIO_FRAME_DURATION_MS / 1000)  # 320 bytes

# VAD (Voice Activity Detection)
VAD_AGGRESSIVENESS: int = 2  # Cambiado de 3 a 2 (menos agresivo, mejor experiencia)
VAD_SILENCE_TIMEOUT_MS: int = 1000  # 1 segundo de silencio (antes 600 ms)
VAD_PRE_RECORD_MS: int = 300  # Guardar 300 ms antes del trigger

# Límites de grabación
TIMEOUT_SILENCIO: float = 1.5  # segundos (consistente con VAD_SILENCE_TIMEOUT_MS/1000)
LIMITE_SEGUNDOS: int = 15

# ----------------------------------------------------------------------
# Logging: archivo de registro
# ----------------------------------------------------------------------
LOG_FILE: Final[Path] = LOGS_DIR / "icaro.log"

# ----------------------------------------------------------------------
# Opcional: Verificar dependencias críticas (solo si se importan librerías)
# ----------------------------------------------------------------------
def check_dependencies() -> None:
    """Verifica que las librerías necesarias estén instaladas."""
    try:
        import pyaudio
        import webrtcvad
        import speech_recognition
        import ollama
        import google.generativeai as genai
    except ImportError as e:
        print(f"Falta una dependencia: {e}")
        sys.exit(1)

# Si se desea, descomentar la siguiente línea (puede ralentizar import)
# check_dependencies()