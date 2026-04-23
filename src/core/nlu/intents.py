import logging
from typing import Optional, Dict, Any
from ...utils.text_utils import normalize_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Respuestas locales (sin IA) para comandos frecuentes
# ---------------------------------------------------------------------------

_LOCAL_PATTERNS = [
    # Hora y fecha
    (["hora", "time", "qué hora"],
     {"intent": "dar_hora_fecha", "target": "hora", "respuesta": "La hora es."}),
    (["fecha", "día", "date", "qué día"],
     {"intent": "dar_hora_fecha", "target": "fecha", "respuesta": "La fecha es."}),
    # Volumen
    (["sube el volumen", "más volumen", "subir volumen"],
     {"intent": "control_volumen", "target": "subir", "respuesta": "Subiendo el volumen."}),
    (["baja el volumen", "menos volumen", "bajar volumen", "baja volumen"],
     {"intent": "control_volumen", "target": "bajar", "respuesta": "Bajando el volumen."}),
    (["silencio", "mute", "silencia", "silenciar", "callate"],
     {"intent": "control_volumen", "target": "silenciar", "respuesta": "Silenciando el audio."}),
    # Calculadora / notepad / VSCode
    (["calculadora", "calcula"],
     {"intent": "abrir_aplicacion", "target": "calculadora", "respuesta": "Abriendo calculadora."}),
    (["notepad", "bloc de notas"],
     {"intent": "abrir_aplicacion", "target": "notepad", "respuesta": "Abriendo Bloc de Notas."}),
    (["código", "vscode", "visual studio"],
     {"intent": "abrir_aplicacion", "target": "vscode", "respuesta": "Abriendo Visual Studio Code."}),
    # Saludos
    (["hola", "hey", "buenas", "qué onda"],
     {"intent": None, "target": None, "respuesta": "Hola, ¿en qué te ayudo?"}),
]

def local_fallback(text: str) -> Optional[Dict[str, Any]]:
    """
    Intenta resolver el comando con reglas locales sin necesidad de IA.
    Devuelve un intent dict o None si no puede resolverlo localmente.
    """
    t = normalize_text(text)

    # 1. Búsqueda directa en patrones estáticos
    for keywords, data in _LOCAL_PATTERNS:
        if any(normalize_text(kw) in t for kw in keywords):
            return data

    # 2. Extracciones dinámicas (YouTube, Google, Abrir app)
    
    # YouTube
    if "youtube" in t or any(w in t for w in ["pon musica", "reproduce", "musica"]):
        query = t.replace("abre", "").replace("pon", "").replace("reproduce", "")
        query = query.replace("musica", "").replace("youtube", "").strip()
        return {"intent": "reproducir_youtube", "target": query, "respuesta": f"Buscando en YouTube: {query}."}

    # Google
    if any(w in t for w in ["busca", "buscame", "google"]):
        query = (
            t.replace("busca", "").replace("buscame", "")
            .replace("en google", "").replace("google", "").strip()
        )
        return {"intent": "buscar_google", "target": query, "respuesta": f"Buscando {query}."}

    # Abrir app genérica
    if any(w in t for w in ["abre", "abrir", "open"]):
        app = t.replace("abre", "").replace("abrir", "").replace("open", "").strip()
        if app:
            return {"intent": "abrir_aplicacion", "target": app, "respuesta": f"Intentando abrir {app}."}

    return None
