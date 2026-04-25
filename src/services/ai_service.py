import json
import re
import logging
from typing import Dict, Any, Optional

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


class AIService:
    """Motor Cognitivo y Router Lógico de Ícaro (optimizado)."""

    # Constantes configurables
    MAX_RESPUESTA_TTS = 300            # caracteres máximos para respuesta hablada
    TIMEOUT_SEGUNDOS = 10               # timeout para llamadas a modelos
    REINTENTOS_LLM = 2                  # reintentos ante fallo transitorio

    # Esquema completo de herramientas (se inyecta en el prompt)
    HERRAMIENTAS_SCHEMA = """
- buscar_google(query="texto")
- control_volumen(accion="subir|bajar|silenciar")
- reproducir_youtube(query="nombre video")
- cerrar_ventana(nombre_ventana="nombre")
- abrir_aplicacion(nombre_app="vscode|word|...")
- crear_carpeta(nombre="nombre")
- escribir_texto(texto="texto")
- dar_hora_fecha(tipo="hora|fecha")
- suspender_equipo()
- hacer_click()
"""

    INTENTS_VALIDOS = {
        "buscar_google", "control_volumen", "reproducir_youtube",
        "cerrar_ventana", "abrir_aplicacion", "crear_carpeta",
        "escribir_texto", "dar_hora_fecha", "suspender_equipo", "hacer_click"
    }

    def __init__(self, memory_manager):
        self.memory = memory_manager
        self.ia_habilitada = False
        self.ollama_habilitado = False
        self.modelo_local = MODELO_LOCAL
        self.client = None          # Cliente Gemini
        self.chat = None            # Sesión de chat Gemini
        self._models_initialized = False

    # ------------------------------------------------------------------
    # Inicialización y chequeo de modelos
    # ------------------------------------------------------------------
    def _ensure_models_initialized(self) -> bool:
        """Inicializa Gemini y/o verifica Ollama una sola vez."""
        if self._models_initialized:
            return self.ia_habilitada or self.ollama_habilitado

        self._models_initialized = True

        # Gemini (nube)
        if genai and types and GEMINI_API_KEY:
            try:
                self.client = genai.Client(api_key=GEMINI_API_KEY)
                self.chat = self.client.chats.create(
                    model="gemini-2.5-flash",
                    config=types.GenerateContentConfig(
                        system_instruction=(
                            "Eres Ícaro, asistente minimalista. "
                            "Habla español neutro. Respuestas cortas (máx 15 palabras). "
                            "Sin markdown."
                        ),
                        temperature=0.2,
                    ),
                )
                self.ia_habilitada = True
                logger.info("Gemini iniciado correctamente.")
            except Exception as exc:
                logger.error(f"Fallo al iniciar Gemini: {exc}")
        else:
            logger.warning("Gemini no configurado (API key o librería faltante).")

        # Ollama (local)
        if ollama:
            try:
                ollama.list()   # prueba conexión
                self.ollama_habilitado = True
                logger.info("Ollama disponible localmente.")
            except Exception as exc:
                logger.warning(f"Ollama no disponible: {exc}")
        else:
            logger.warning("Librería ollama no instalada.")

        return self.ia_habilitada or self.ollama_habilitado

    # ------------------------------------------------------------------
    # Llamada unificada a LLM (con reintentos y extracción de JSON)
    # ------------------------------------------------------------------
    def _call_llm(self, prompt: str, usar_ollama: bool = True) -> Optional[Dict[str, Any]]:
        """
        Intenta obtener un JSON desde Ollama (si está habilitado y usar_ollama=True)
        y luego desde Gemini. Retorna el dict o None si ambos fallan.
        """
        # Helper para extraer JSON de una respuesta de texto
        def extraer_json(texto: str) -> Optional[Dict]:
            # Busca el primer bloque que parece JSON: { ... }
            match = re.search(r'\{[^{}]*\}(?:\s*\{[^{}]*\})*', texto, re.DOTALL)
            if not match:
                # Intenta con algo más permisivo
                match = re.search(r'\{.*\}', texto, re.DOTALL)
            if match:
                candidato = match.group(0)
                try:
                    return json.loads(candidato)
                except json.JSONDecodeError:
                    logger.debug(f"JSON inválido encontrado: {candidato[:100]}")
            return None

        # 1) Ollama
        if self.ollama_habilitado and usar_ollama:
            for intento in range(self.REINTENTOS_LLM):
                try:
                    res = ollama.chat(
                        model=self.modelo_local,
                        messages=[{"role": "user", "content": prompt}],
                        format="json",   # fuerza JSON en teoría
                        options={
                            "temperature": 0.0,
                            "num_predict": 150,
                            "top_p": 0.9,
                            "stop": ["\n```", "```"],
                        }
                    )
                    contenido = res["message"]["content"]
                    datos = extraer_json(contenido)
                    if datos:
                        logger.info(f"Ollama respondió (intento {intento+1}): {datos}")
                        return datos
                    else:
                        logger.warning(f"Respuesta de Ollama sin JSON válido: {contenido[:100]}")
                except Exception as exc:
                    logger.warning(f"Ollama falló (intento {intento+1}): {exc}")
                    # Espera progresiva
                    if intento < self.REINTENTOS_LLM - 1:
                        import time
                        time.sleep(0.5 ** (intento + 1))
            logger.warning("Ollama no dio respuesta válida después de reintentos.")

        # 2) Gemini
        if self.ia_habilitada:
            for intento in range(self.REINTENTOS_LLM):
                try:
                    # Si la sesión de chat expiró, la recreamos
                    if self.chat is None:
                        self.chat = self.client.chats.create(
                            model="gemini-2.5-flash",
                            config=types.GenerateContentConfig(
                                system_instruction=(
                                    "Eres Ícaro, asistente para programación avanzada. "
                                    "Respuesta corta, solo JSON, sin texto adicional."
                                ),
                                temperature=0.2,
                            ),
                        )
                    res = self.chat.send_message(prompt)
                    texto_limpio = res.text.strip()
                    datos = extraer_json(texto_limpio)
                    if datos:
                        logger.info(f"Gemini respondió: {datos}")
                        return datos
                    else:
                        logger.warning(f"Gemini devolvió sin JSON: {texto_limpio[:100]}")
                except Exception as exc:
                    logger.error(f"Gemini falló (intento {intento+1}): {exc}")
                    self.chat = None   # forzar recreación si es error de sesión
                    if intento < self.REINTENTOS_LLM - 1:
                        import time
                        time.sleep(1)
        return None

    # ------------------------------------------------------------------
    # Enrutamiento principal
    # ------------------------------------------------------------------
    def route_command(self, text: str) -> Dict[str, Any]:
        """
        Pipeline:
          1. Respuesta local rápida (local_fallback)
          2. Ollama local (prioridad)
          3. Gemini nube
          4. Fallback humanoide
        """
        # --- Paso 1: local inmediato (sin IA) ---
        local = local_fallback(text)
        if local:
            logger.info(f"Respuesta LOCAL para: '{text}'")
            return self._sanitize_response(local)

        # --- Paso 2: inicializar IA si no lo estaba ---
        ai_available = self._ensure_models_initialized()
        if not ai_available:
            logger.warning("Ningún modelo IA disponible.")
            return {
                "intent": None,
                "target": None,
                "respuesta": "Mis sistemas de IA están offline. Puedo hacer cosas básicas como dar la hora o abrir apps. ¿Qué necesitas?"
            }

        # --- Construir prompt con contexto histórico y herramientas ---
        # Obtener últimas 2 interacciones de la memoria (si existe)
        contexto = ""
        if self.memory:
            try:
                historial = self.memory.get_recent(2)  # asumo método existente
                if historial:
                    contexto = "Conversación reciente:\n" + "\n".join(
                        f"Usuario: {h['input']}\nÍcaro: {h['response']}" for h in historial
                    ) + "\n"
            except Exception as e:
                logger.debug(f"No se pudo acceder a memoria: {e}")

        # Escapar texto del usuario para JSON
        user_text_escaped = json.dumps(text, ensure_ascii=False)

        prompt = f"""\
{contexto}
{self.HERRAMIENTAS_SCHEMA}

Instrucción: Eres Ícaro. Recibes el comando del usuario. Responde ÚNICAMENTE con un JSON válido que contenga:
- "intent": uno de estos valores exactos: {', '.join(self.INTENTS_VALIDOS)} (si no aplica, usa null)
- "target": el objeto de la acción (ej. nombre de app, query de búsqueda, etc.) o null
- "respuesta": una frase corta de confirmación (menos de 15 palabras, en español)

Ejemplo:
Usuario: "abre el bloc de notas"
Salida: {{"intent": "abrir_aplicacion", "target": "bloc de notas", "respuesta": "Abriendo bloc de notas."}}

Ahora procesa:
Usuario: {user_text_escaped}
Salida:"""

        # --- Paso 3: LLM (Ollama primero, Gemini después) ---
        datos = self._call_llm(prompt, usar_ollama=True)
        if datos:
            return self._parse_routing_data(datos)

        # --- Paso 4: fallback total ---
        return {
            "intent": None,
            "target": None,
            "respuesta": "Lo siento, no pude procesar eso ahora mismo. ¿Puedes repetirlo?"
        }

    # ------------------------------------------------------------------
    # Parseo y sanitización de respuestas
    # ------------------------------------------------------------------
    def _parse_routing_data(self, datos: Dict[str, Any]) -> Dict[str, Any]:
        """Extrae y valida intent, target, respuesta. Trunca respuesta para TTS."""
        # Normalizar intent
        intent = datos.get("intent")
        if isinstance(intent, str):
            intent = intent.strip().lower()
            if intent == "null" or intent not in self.INTENTS_VALIDOS:
                intent = None
        else:
            intent = None

        # Normalizar target
        target = datos.get("target")
        if target is None:
            # soporte legacy: buscar dentro de params si existe (por compatibilidad)
            params = datos.get("params", {})
            if "nombre_app" in params:
                target = params["nombre_app"]
            elif "query" in params:
                target = params["query"]
        if isinstance(target, dict):
            target = next(iter(target.values())) if target else None
        if not isinstance(target, str):
            target = str(target) if target is not None else ""

        # Respuesta y truncado inteligente
        respuesta = datos.get("respuesta", "Entendido.")
        if not isinstance(respuesta, str):
            respuesta = str(respuesta)

        # Truncar para TTS, respetando límite de caracteres y cortando en punto o coma
        if len(respuesta) > self.MAX_RESPUESTA_TTS:
            truncado = respuesta[:self.MAX_RESPUESTA_TTS]
            # Buscar último separador de oración
            for sep in (". ", "? ", "! ", ", "):
                pos = truncado.rfind(sep)
                if pos > self.MAX_RESPUESTA_TTS // 2:
                    truncado = truncado[:pos + 1]
                    break
            respuesta = truncado.strip() + ("." if not truncado.endswith((".", "?", "!")) else "")
            logger.debug(f"Respuesta truncada de {len(respuesta)} a {len(truncado)} caracteres.")

        return {"intent": intent, "target": target, "respuesta": respuesta}

    def _sanitize_response(self, resp: Dict[str, Any]) -> Dict[str, Any]:
        """Asegura que la respuesta local tenga la estructura correcta."""
        return {
            "intent": resp.get("intent"),
            "target": resp.get("target", ""),
            "respuesta": resp.get("respuesta", "")
        }

    # ------------------------------------------------------------------
    # Conversación directa (sin acciones)
    # ------------------------------------------------------------------
    def summarize(self, text: str) -> str:
        """Respuesta conversacional usando la misma lógica prioritaria."""
        if not self._ensure_models_initialized():
            return "Las capacidades de IA están apagadas."

        prompt = f"Responde brevemente en español: {json.dumps(text)}"
        datos = self._call_llm(prompt, usar_ollama=True)
        if datos and "respuesta" in datos:
            return datos["respuesta"]
        return "No pude generar una respuesta en este momento."

    def fallback_response(self) -> str:
        return "No pude entender eso, ¿puedes repetirlo?"
