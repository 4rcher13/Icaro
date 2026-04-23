import json
import time
import logging
from ..utils.text_utils import normalize_text
from ..core.nlu.intents import local_fallback

try:
    import google.genai as genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

try:
    import ollama
except ImportError:
    ollama = None

from ..config.settings import GEMINI_API_KEY, MODELO_LOCAL

logger = logging.getLogger(__name__)




# ---------------------------------------------------------------------------

class AIService:
    """Motor Cognitivo y Router Lógico de Ícaro."""

    def __init__(self, memory_manager):
        self.memory = memory_manager
        self.ia_habilitada = False
        self.ollama_habilitado = False
        self.modelo_local = MODELO_LOCAL
        self.client = None
        self.chat = None
        self._models_initialized = False

        self.herramientas_schema = """\
- buscar_google(query="texto a buscar")
- control_volumen(accion="subir" o "bajar" o "silenciar")
- reproducir_youtube(query="nombre video")
- cerrar_ventana(nombre_ventana="nombre")
- abrir_aplicacion(nombre_app="nombre de aplicacion como vscode, word, etc.")
- crear_carpeta(nombre="nombre")
- escribir_texto(texto="texto a escribir")
- dar_hora_fecha(tipo="hora" o "fecha")
- suspender_equipo()
- hacer_click()
"""

    # ------------------------------------------------------------------

    def _ensure_models_initialized(self) -> bool:
        if self._models_initialized:
            return self.ia_habilitada or self.ollama_habilitado

        self._models_initialized = True

        # Nube: Gemini
        if genai and types and GEMINI_API_KEY:
            try:
                self.client = genai.Client(api_key=GEMINI_API_KEY)
                self.chat = self.client.chats.create(
                    model="gemini-2.0-flash",
                    config=types.GenerateContentConfig(
                        system_instruction=(
                            "Eres Ícaro, asistente inteligente. "
                            "Habla en español, de forma natural, directa y concisa."
                        ),
                        temperature=0.7,
                    ),
                )
                self.ia_habilitada = True
                logger.info("Gemini iniciado correctamente.")
            except Exception as exc:
                logger.error(f"Fallo Gemini: {exc}")
        else:
            logger.warning("Gemini no configurado (sin API KEY o librería).")

        # Local: Ollama
        if ollama:
            try:
                ollama.list()
                self.ollama_habilitado = True
                logger.info("Ollama disponible.")
            except Exception:
                logger.warning("Ollama offline o no instalado.")

        return self.ia_habilitada or self.ollama_habilitado

    # ------------------------------------------------------------------

    def route_command(self, text: str) -> dict:
        """
        Pipeline de enrutamiento:
          1. Respuesta local rápida (keywords, sin latencia)
          2. Ollama local (si está disponible)
          3. Gemini nube (fallback)
          4. Respuesta local básica (si todo falla)
        """
        # ── Paso 1: Respuesta local inmediata ──
        local = local_fallback(text)
        if local:
            logger.info(f"Respuesta LOCAL para: '{text}'")
            return local

        # ── Paso 2: Intentar inicializar modelos ──
        ai_available = self._ensure_models_initialized()
        if not ai_available:
            logger.warning("Ningún modelo de IA disponible, usando fallback local extendido.")
            return {
                "intent": None,
                "target": None,
                "respuesta": "Mis sistemas de IA están offline, pero puedo hacer cosas básicas como decirte la hora o abrir apps. ¿Qué necesitas?",
            }

        prompt = f"""\
Comando del usuario: "{text}"
HERRAMIENTAS disponibles:
{self.herramientas_schema}
Devuelve EXCLUSIVAMENTE un JSON:
{{"intent": "nombre_o_null", "target": "parametro", "respuesta": "que dirias tu"}}
Si no aplica ninguna herramienta, usa intent null y responde normalmente.
NO uses bloques ```json, solo texto plano JSON.
"""
        # ── Paso 3: Ollama (local, rápido) ──
        if self.ollama_habilitado:
            try:
                res = ollama.chat(
                    model=self.modelo_local,
                    messages=[{"role": "user", "content": prompt}],
                    format="json",
                    options={"temperature": 0.1, "num_predict": 150},
                )
                datos = json.loads(res["message"]["content"])
                logger.info(f"Ollama respondió: {datos}")
                return self._parse_routing_data(datos)
            except Exception as exc:
                logger.warning(f"Ollama falló: {exc}. Probando Gemini...")

        # ── Paso 4: Gemini (nube) ──
        if self.ia_habilitada:
            try:
                res = self.chat.send_message(prompt)
                texto_limpio = res.text.replace("```json", "").replace("```", "").strip()
                datos = json.loads(texto_limpio)
                logger.info(f"Gemini respondió: {datos}")
                return self._parse_routing_data(datos)
            except Exception as exc:
                logger.error(f"Gemini falló: {exc}")

        # ── Fallback total ──
        return {
            "intent": None,
            "target": None,
            "respuesta": "Lo siento, no pude procesar eso ahora mismo.",
        }

    def _parse_routing_data(self, datos: dict) -> dict:
        intent = datos.get("intent")
        target = datos.get("target") or datos.get("params", {}).get("nombre_app", "")
        if isinstance(target, dict) and target:
            target = list(target.values())[0]
        respuesta = datos.get("respuesta", "Entendido.")
        if intent in ("null", "None", "", None):
            intent = None
        return {"intent": intent, "target": target, "respuesta": respuesta}

    def summarize(self, text: str) -> str:
        """Respuesta directa de conversación sin lanzar acciones."""
        if not self._ensure_models_initialized():
            return "Las capacidades de IA están apagadas."
        if self.ia_habilitada:
            try:
                return self.chat.send_message(text).text or "Sin respuesta."
            except Exception:
                pass
        return "Resumen no disponible ahora."

    def fallback_response(self) -> str:
        return "No pude entender eso, ¿puedes repetirlo?"
