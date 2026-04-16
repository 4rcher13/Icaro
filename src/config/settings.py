import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Base del proyecto de forma absoluta
BASE_DIR = Path(__file__).resolve().parent.parent

# --- Claves y Auth ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- Variables de IA & Lógica ---
WAKE_WORD = {"icaro", "si claro", "vicaro", "y creo", "y claro", "y caro", "claro", "y quiero"}
MODELO_LOCAL = "qwen2.5:3b"

# --- Historial y Sistema de Archivos ---
MAX_HISTORY = 40
HISTORY_FILE = BASE_DIR / "data" / "historial.json"

# --- Configuración Visual/Audio ---
VOICE_RATE = 155
TIMEOUT_SILENCIO = 1.5
LIMITE_SEGUNDOS = 15

# --- Logging ---
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "icaro.log"
